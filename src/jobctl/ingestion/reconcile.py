"""Resume fact reconciliation against the existing graph."""

from __future__ import annotations

import sqlite3
import json
from collections import Counter
from difflib import SequenceMatcher
from typing import Any

from jobctl.db.graph import get_node, search_nodes
from jobctl.ingestion.schemas import FactReconciliation, NodeMatch, ResumeReconciliationResult
from jobctl.llm.schemas import ExtractedFact
from jobctl.rag.store import VectorFilter, VectorStore


def find_candidate_nodes_for_fact(
    conn: sqlite3.Connection,
    fact: ExtractedFact,
    llm_client: Any,
    vector_store: VectorStore,
    limit: int = 5,
) -> list[NodeMatch]:
    """Return ranked deterministic candidates for a resume fact."""
    entity_type = _norm_type(fact.entity_type)
    entity_name = _norm_text(fact.entity_name)
    candidates: dict[str, NodeMatch] = {}

    search_terms = [fact.entity_name]
    for token in entity_name.split():
        if len(token) >= 4:
            search_terms.append(token)

    for term in dict.fromkeys(search_terms):
        for node in search_nodes(conn, type=entity_type, name_contains=term):
            _merge_candidate(candidates, _match_from_node(node, fact))

    for node in search_nodes(conn, type=entity_type):
        similarity = _name_similarity(entity_name, _norm_text(node["name"]))
        if similarity >= 0.72:
            match = _match_from_node(node, fact)
            match.score = max(match.score, similarity * 0.8)
            match.confidence = max(match.confidence, similarity)
            match.signals.append(f"fuzzy_name:{similarity:.2f}")
            _merge_candidate(candidates, match)

    if llm_client is not None and hasattr(llm_client, "get_embedding"):
        try:
            embedding = llm_client.get_embedding(_fact_text(fact))
            hits = vector_store.search(
                embedding,
                top_k=limit,
                filters=VectorFilter(node_type=entity_type),
            )
            for hit in hits:
                try:
                    node = get_node(conn, hit.node_id)
                except KeyError:
                    continue
                score = max(0.0, float(hit.score))
                match = _match_from_node(node, fact)
                match.score = max(match.score, score)
                match.confidence = max(match.confidence, score)
                match.signals.append(f"qdrant:{hit.score:.3f}")
                _merge_candidate(candidates, match)
        except Exception:
            pass

    return sorted(candidates.values(), key=lambda match: match.score, reverse=True)[:limit]


def classify_fact_against_candidates(
    fact: ExtractedFact,
    candidates: list[NodeMatch],
    llm_client: Any,
) -> FactReconciliation:
    if not candidates:
        return _new(fact, "No bounded graph candidates found.")
    if llm_client is None or not hasattr(llm_client, "chat_structured"):
        return _fallback_classification(fact, candidates)

    messages = [
        {
            "role": "system",
            "content": (
                "Classify one extracted resume fact against the provided bounded graph "
                "candidates. Be conservative. Exact or near-exact same facts are "
                "duplicates. Additive details are updates. Multiple plausible matches "
                "are ambiguous. Contradictions are conflicts. Absent matches are new. "
                "Do not invent facts or silently strengthen positioning."
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "fact": fact.model_dump(),
                    "candidates": [candidate.model_dump() for candidate in candidates],
                }
            ),
        },
    ]
    try:
        result = llm_client.chat_structured(messages, response_format=FactReconciliation)
    except Exception:
        return _fallback_classification(fact, candidates)
    if not result.candidate_matches:
        result.candidate_matches = candidates
    if not result.source_fact:
        result.source_fact = fact
    return result


def reconcile_resume_facts(
    conn: sqlite3.Connection,
    facts: list[ExtractedFact],
    llm_client: Any,
    source_ref: str,
    *,
    vector_store: VectorStore,
) -> ResumeReconciliationResult:
    reconciliations: list[FactReconciliation] = []
    for fact in facts:
        candidates = find_candidate_nodes_for_fact(
            conn,
            fact,
            llm_client,
            vector_store=vector_store,
        )
        deterministic = _deterministic_classification(fact, candidates)
        if deterministic is None:
            deterministic = classify_fact_against_candidates(fact, candidates, llm_client)
        reconciliations.append(deterministic)

    counts = Counter(item.classification for item in reconciliations)
    for classification in ("duplicate", "update", "new", "ambiguous", "conflict"):
        counts.setdefault(classification, 0)
    return ResumeReconciliationResult(
        source_ref=source_ref,
        facts=reconciliations,
        summary_counts=dict(counts),
    )


def _deterministic_classification(
    fact: ExtractedFact, candidates: list[NodeMatch]
) -> FactReconciliation | None:
    if not candidates:
        return _new(fact, "No graph candidates found.")
    best = candidates[0]
    same_name = _norm_text(best.name) == _norm_text(fact.entity_name)
    same_text = _norm_text(best.text) == _norm_text(fact.text_representation)
    if same_name and same_text:
        return FactReconciliation(
            source_fact=fact,
            classification="duplicate",
            confidence=0.99,
            matched_node_ids=[best.node_id],
            candidate_matches=candidates,
            reason="Exact type, name, and text match.",
            proposed_action="skip",
            requires_confirmation=False,
        )
    if best.score >= 0.92 and same_text:
        return FactReconciliation(
            source_fact=fact,
            classification="duplicate",
            confidence=best.confidence,
            matched_node_ids=[best.node_id],
            candidate_matches=candidates,
            reason="High-confidence candidate with identical text.",
            proposed_action="skip",
            requires_confirmation=False,
        )
    return None


def _fallback_classification(
    fact: ExtractedFact, candidates: list[NodeMatch]
) -> FactReconciliation:
    best = candidates[0]
    if best.score >= 0.85:
        return FactReconciliation(
            source_fact=fact,
            classification="update",
            confidence=min(best.confidence or best.score, 0.9),
            matched_node_ids=[best.node_id],
            candidate_matches=candidates,
            reason="Strong name match but text differs; treat as additive update.",
            proposed_action="create_update_proposal",
            requires_confirmation=True,
        )
    if len(candidates) > 1 and candidates[0].score - candidates[1].score < 0.12:
        return FactReconciliation(
            source_fact=fact,
            classification="ambiguous",
            confidence=best.confidence,
            matched_node_ids=[candidate.node_id for candidate in candidates[:2]],
            candidate_matches=candidates,
            reason="Multiple bounded candidates have similar scores.",
            proposed_action="ask_user",
            requires_confirmation=True,
        )
    return _new(fact, "No high-confidence existing graph match.", candidates)


def _new(
    fact: ExtractedFact,
    reason: str,
    candidates: list[NodeMatch] | None = None,
) -> FactReconciliation:
    return FactReconciliation(
        source_fact=fact,
        classification="new",
        confidence=0.95 if not candidates else 0.7,
        candidate_matches=candidates or [],
        reason=reason,
        proposed_action="add_fact",
        requires_confirmation=False,
    )


def _match_from_node(node: dict[str, Any], fact: ExtractedFact) -> NodeMatch:
    name_similarity = _name_similarity(_norm_text(fact.entity_name), _norm_text(node["name"]))
    text_similarity = _name_similarity(
        _norm_text(fact.text_representation), _norm_text(node["text_representation"])
    )
    exact_name = _norm_text(fact.entity_name) == _norm_text(node["name"])
    score = max(name_similarity, text_similarity * 0.85)
    signals = [f"name:{name_similarity:.2f}", f"text:{text_similarity:.2f}"]
    if exact_name:
        score = max(score, 0.95)
        signals.append("exact_name")
    return NodeMatch(
        node_id=node["id"],
        node_type=node["type"],
        name=node["name"],
        text=node["text_representation"],
        score=score,
        confidence=score,
        signals=signals,
    )


def _merge_candidate(candidates: dict[str, NodeMatch], match: NodeMatch) -> None:
    existing = candidates.get(match.node_id)
    if existing is None or match.score > existing.score:
        candidates[match.node_id] = match
        return
    existing.signals.extend(signal for signal in match.signals if signal not in existing.signals)


def _norm_type(value: str) -> str:
    return value.strip().lower().replace(" ", "_")


def _norm_text(value: str) -> str:
    return " ".join(value.casefold().split())


def _name_similarity(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    return SequenceMatcher(a=left, b=right).ratio()


def _fact_text(fact: ExtractedFact) -> str:
    return f"{fact.entity_type}: {fact.entity_name}\n{fact.text_representation}"


__all__ = [
    "classify_fact_against_candidates",
    "find_candidate_nodes_for_fact",
    "reconcile_resume_facts",
]
