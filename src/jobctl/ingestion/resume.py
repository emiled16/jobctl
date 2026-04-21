"""Resume file parsing and fact persistence."""

from __future__ import annotations

import logging
import os
import shlex
import sqlite3
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import yaml
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.syntax import Syntax

from jobctl.core.events import (
    AsyncEventBus,
    IngestErrorEvent,
    IngestProgressEvent,
)
from jobctl.core.jobs.store import BackgroundJobStore
from jobctl.curation.proposals import CurationProposalStore
from jobctl.db.graph import (
    add_edge,
    add_edge_if_missing,
    add_node,
    add_node_source,
    get_node,
    search_nodes,
    update_node,
)
from jobctl.config import JobctlConfig
from jobctl.ingestion.questions import RefinementQuestionStore
from jobctl.ingestion.reconcile import reconcile_resume_facts
from jobctl.ingestion.refinement import persist_refinement_questions, plan_refinement_questions
from jobctl.ingestion.schemas import FactReconciliation, ResumeReconciliationResult
from jobctl.llm.schemas import ExtractedFact, ExtractedProfile
from jobctl.rag.indexing import index_node
from jobctl.rag.store import VectorStore

logger = logging.getLogger(__name__)


class UnsupportedFormatError(ValueError):
    """Raised when a resume file extension is not supported."""


SUPPORTED_RESUME_EXTENSIONS = frozenset({".txt", ".md", ".pdf", ".docx"})

console = Console()

_EXTRACTED_PROFILE_SCHEMA_GUIDANCE = (
    "Return strict JSON matching this schema:\n"
    "{\n"
    '  "facts": [\n'
    "    {\n"
    '      "entity_type": string,\n'
    '      "entity_name": string,\n'
    '      "relation": string | null,\n'
    '      "related_to": string | null,\n'
    '      "properties": object,\n'
    '      "text_representation": string\n'
    "    }\n"
    "  ]\n"
    "}\n"
    "Allowed fact keys are exactly: entity_type, entity_name, relation, related_to, "
    "properties, text_representation. Do not use legacy keys like type, name, "
    "description, source_context, start_date, end_date, company, metrics."
)


def read_resume(file_path: Path) -> str:
    suffix = file_path.suffix.lower()
    if suffix in {".txt", ".md"}:
        return file_path.read_text(encoding="utf-8")
    if suffix == ".pdf":
        return _read_pdf(file_path)
    if suffix == ".docx":
        return _read_docx(file_path)
    raise UnsupportedFormatError(f"Unsupported resume format: {suffix or '<none>'}")


def extract_facts_from_resume(resume_text: str, llm_client) -> ExtractedProfile:
    messages = [
        {
            "role": "system",
            "content": (
                "Extract a career knowledge graph from the resume. Create facts for roles, "
                "companies, skills, achievements, education, and projects. Use relation and "
                "related_to when a fact should connect to another entity by name. Keep "
                "properties structured with dates, metrics, descriptions, and source context.\n\n"
                + _EXTRACTED_PROFILE_SCHEMA_GUIDANCE
            ),
        },
        {"role": "user", "content": resume_text},
    ]
    return llm_client.chat_structured(messages, response_format=ExtractedProfile)


def persist_facts(
    conn: sqlite3.Connection,
    facts: list[ExtractedFact],
    llm_client,
    interactive: bool = True,
    *,
    vector_store: VectorStore,
    config: JobctlConfig | None = None,
    bus: AsyncEventBus | None = None,
    store: BackgroundJobStore | None = None,
    job_id: str | None = None,
) -> int:
    """Persist ``facts`` into the graph and emit progress events.

    When ``bus`` + ``store`` + ``job_id`` are provided the function writes a
    checkpoint per fact and publishes :class:`IngestProgressEvent`s plus
    :class:`IngestErrorEvent`s. Legacy callers that omit those arguments keep
    the original Rich-prompt flow for backwards compatibility while the v2
    agent migrates.
    """
    persisted_count = 0
    total = len(facts)
    for index, fact in enumerate(facts, start=1):
        external_id = f"{fact.entity_type}:{fact.entity_name}"
        if store is not None and job_id is not None:
            if store.is_item_seen(job_id, external_id=external_id):
                _publish_progress(bus, job_id, index, total, fact.entity_name + " (skipped)")
                continue

        accepted_fact = _confirm_fact(fact) if interactive and bus is None else fact
        if accepted_fact is None:
            if store is not None and job_id is not None:
                store.mark_item_done(job_id, external_id=external_id, status="skipped")
            continue

        try:
            entity_type = accepted_fact.entity_type.lower()
            node_id = add_node(
                conn,
                entity_type,
                accepted_fact.entity_name,
                accepted_fact.properties,
                accepted_fact.text_representation,
            )
            _index_node_best_effort(conn, vector_store, node_id, llm_client, config=config)

            related_node_id = _resolve_related_node(
                conn,
                accepted_fact,
                llm_client,
                vector_store=vector_store,
                config=config,
            )
            if related_node_id is not None and accepted_fact.relation:
                source_id, target_id = _edge_direction(
                    conn,
                    node_id,
                    related_node_id,
                    accepted_fact.relation,
                    entity_type,
                )
                add_edge(conn, source_id, target_id, accepted_fact.relation, {})

            persisted_count += 1
            if store is not None and job_id is not None:
                store.mark_item_done(job_id, external_id=external_id)
            _publish_progress(bus, job_id, index, total, accepted_fact.entity_name)
        except Exception as exc:  # noqa: BLE001 - surface to bus, do not swallow
            if logger.isEnabledFor(logging.DEBUG):
                logger.exception("persist_facts failed on %s", external_id)
            else:
                logger.error("persist_facts failed on %s: %s", external_id, exc)
            if bus is not None:
                bus.publish(IngestErrorEvent(source="resume", error=str(exc), job_id=job_id))

    return persisted_count


def persist_reconciled_resume_facts(
    conn: sqlite3.Connection,
    reconciliation: ResumeReconciliationResult,
    llm_client,
    source_ref: str,
    *,
    bus: AsyncEventBus | None = None,
    store: BackgroundJobStore | None = None,
    job_id: str | None = None,
    proposal_store: CurationProposalStore | None = None,
    vector_store: VectorStore,
    config: JobctlConfig | None = None,
) -> dict[str, int]:
    """Persist safe reconciled facts and create review proposals for updates."""
    summary = {"added": 0, "duplicates": 0, "updates_proposed": 0, "skipped": 0}
    proposal_store = proposal_store or CurationProposalStore(conn)
    total = len(reconciliation.facts)

    for index, item in enumerate(reconciliation.facts, start=1):
        fact = item.source_fact
        external_id = f"{fact.entity_type}:{fact.entity_name}"
        if item.classification == "duplicate":
            summary["duplicates"] += 1
            if store is not None and job_id is not None:
                store.mark_item_done(job_id, external_id=external_id, status="duplicate")
            _publish_progress(bus, job_id, index, total, fact.entity_name + " (duplicate)")
            continue
        if item.classification == "update":
            _create_update_proposal(proposal_store, item, source_ref)
            summary["updates_proposed"] += 1
            _publish_progress(bus, job_id, index, total, fact.entity_name + " (proposal)")
            continue
        if item.classification != "new" or item.confidence < 0.6 or item.requires_confirmation:
            summary["skipped"] += 1
            _publish_progress(bus, job_id, index, total, fact.entity_name + " (needs review)")
            continue

        node_id, created = _persist_single_fact(
            conn,
            fact,
            llm_client,
            source_ref,
            item.confidence,
            vector_store=vector_store,
            config=config,
        )
        if store is not None and job_id is not None:
            store.mark_item_done(job_id, external_id=external_id, node_id=node_id)
        if created:
            summary["added"] += 1
        _publish_progress(bus, job_id, index, total, fact.entity_name)

    return summary


def ingest_resume_enriched(
    conn: sqlite3.Connection,
    resume_path: Path,
    llm_client,
    *,
    bus: AsyncEventBus | None = None,
    store: BackgroundJobStore | None = None,
    job_id: str | None = None,
    proposal_store: CurationProposalStore | None = None,
    question_store: RefinementQuestionStore | None = None,
    vector_store: VectorStore,
    config: JobctlConfig | None = None,
) -> dict[str, object]:
    """Read, extract, reconcile, persist, and plan refinement for a resume."""
    text = read_resume(resume_path)
    profile = extract_facts_from_resume(text, llm_client)
    source_ref = str(resume_path)
    reconciliation = reconcile_resume_facts(
        conn,
        profile.facts,
        llm_client,
        source_ref,
        vector_store=vector_store,
    )
    persistence = persist_reconciled_resume_facts(
        conn,
        reconciliation,
        llm_client,
        source_ref,
        bus=bus,
        store=store,
        job_id=job_id,
        proposal_store=proposal_store,
        vector_store=vector_store,
        config=config,
    )
    promoted_skills = promote_resume_skill_nodes(
        conn,
        llm_client,
        source_ref,
        vector_store=vector_store,
        config=config,
    )
    normalized_edges = normalize_resume_edges(conn)
    inferred_edges = infer_resume_edges(conn)
    question_store = question_store or RefinementQuestionStore(conn)
    questions = plan_refinement_questions(conn, reconciliation, llm_client)
    question_ids = persist_refinement_questions(question_store, questions)
    return {
        "facts_extracted": len(profile.facts),
        "facts_added": persistence["added"],
        "duplicates_skipped": persistence["duplicates"],
        "updates_proposed": persistence["updates_proposed"],
        "facts_skipped": persistence["skipped"],
        "edges_inferred": inferred_edges,
        "skills_promoted": promoted_skills["skills_created"],
        "skill_edges_added": promoted_skills["skill_edges_added"],
        "edges_normalized": normalized_edges,
        "refinement_questions_saved": len(question_ids),
        "pending_question_ids": question_ids,
        "reconciliation_counts": reconciliation.summary_counts,
        "can_start_refinement": bool(question_ids),
    }


def _persist_single_fact(
    conn: sqlite3.Connection,
    fact: ExtractedFact,
    llm_client,
    source_ref: str,
    confidence: float,
    *,
    vector_store: VectorStore,
    config: JobctlConfig | None,
) -> tuple[str, bool]:
    entity_type = fact.entity_type.lower()
    existing = [
        node
        for node in search_nodes(conn, type=entity_type, name_contains=fact.entity_name)
        if node["name"].lower() == fact.entity_name.lower()
        and node["text_representation"].lower() == fact.text_representation.lower()
    ]
    if existing:
        node_id = existing[0]["id"]
        created = False
    else:
        node_id = add_node(
            conn,
            entity_type,
            fact.entity_name,
            fact.properties,
            fact.text_representation,
        )
        created = True
        _index_node_best_effort(conn, vector_store, node_id, llm_client, config=config)
    add_node_source(conn, node_id, "resume", source_ref, confidence, fact.text_representation)

    related_node_id = _resolve_related_node(
        conn,
        fact,
        llm_client,
        vector_store=vector_store,
        config=config,
    )
    if related_node_id is not None and fact.relation:
        relation = normalize_resume_relation(fact.relation, entity_type)
        source_id, target_id = _edge_direction(
            conn, node_id, related_node_id, relation, entity_type
        )
        add_edge_if_missing(conn, source_id, target_id, relation, {})
    return node_id, created


def infer_resume_edges(conn: sqlite3.Connection) -> int:
    """Infer conservative graph edges from resume node text/properties.

    This covers resumes where extraction produced correct nodes but omitted
    ``relation``/``related_to`` fields. It only links when company,
    institution, or role evidence is explicit in node text/properties.
    """
    nodes = search_nodes(conn)
    by_type: dict[str, list[dict[str, Any]]] = {}
    for node in nodes:
        by_type.setdefault(node["type"], []).append(node)

    added = 0
    person = _first(by_type.get("person", []))
    companies = by_type.get("company", [])
    roles = by_type.get("role", [])
    institutions = by_type.get("education_institution", [])

    role_company: dict[str, str] = {}
    for role in roles:
        company = _find_named_node(_node_evidence(role), companies, allow_aliases=True)
        if company is None:
            continue
        if add_edge_if_missing(conn, role["id"], company["id"], "worked_at", {}) is not None:
            added += 1
        role_company[role["id"]] = company["id"]
        if person is not None:
            if add_edge_if_missing(conn, person["id"], role["id"], "held_role", {}) is not None:
                added += 1

    for fact_type, relation in (
        ("achievement", "achieved"),
        ("project", "worked_on"),
    ):
        for node in by_type.get(fact_type, []):
            role = _find_role_for_node(node, roles, companies, role_company)
            if role is not None:
                if add_edge_if_missing(conn, role["id"], node["id"], relation, {}) is not None:
                    added += 1

    for skill in by_type.get("skill", []):
        role = _find_role_for_node(skill, roles, companies, role_company)
        if role is not None:
            if add_edge_if_missing(conn, role["id"], skill["id"], "used_skill", {}) is not None:
                added += 1

    for education in by_type.get("education", []):
        institution = _find_named_node(_node_evidence(education), institutions)
        if institution is not None:
            if (
                add_edge_if_missing(conn, education["id"], institution["id"], "studied_at", {})
                is not None
            ):
                added += 1
        if person is not None:
            if add_edge_if_missing(conn, person["id"], education["id"], "earned", {}) is not None:
                added += 1

    if person is not None:
        for publication in by_type.get("publication", []):
            if (
                add_edge_if_missing(conn, person["id"], publication["id"], "authored", {})
                is not None
            ):
                added += 1

    return added


_TECH_PROPERTY_KEYS = {
    "technology",
    "technologies",
    "tool",
    "tools",
    "framework",
    "frameworks",
    "library",
    "libraries",
    "stack",
    "cloud",
    "infrastructure",
    "deployment",
    "runtime",
    "methods",
    "platform",
    "platforms",
}

_SKILL_CONTAINER_TYPES = {"role", "achievement", "project", "publication", "education"}

_RELATION_ALIASES = {
    "built_at": "worked_at",
    "delivered_at": "worked_at",
    "designed_at": "worked_at",
    "led_at": "worked_at",
    "managed_at": "worked_at",
    "conducted_at": "worked_at",
    "earned_at": "studied_at",
    "published_in": "authored",
    "proposed_by": "worked_on",
    "implemented_by": "worked_on",
    "contributed_to": "achieved",
    "used_in": "used_skill",
    "uses": "used_skill",
    "used": "used_skill",
}


def normalize_resume_relation(relation: str, entity_type: str | None = None) -> str:
    normalized = relation.strip().lower().replace(" ", "_").replace("-", "_")
    if normalized in _RELATION_ALIASES:
        return _RELATION_ALIASES[normalized]
    if entity_type == "skill" and normalized in {"related_to", "associated_with"}:
        return "used_skill"
    return normalized


def normalize_resume_edges(conn: sqlite3.Connection) -> int:
    """Normalize existing resume edge relation labels in place."""
    rows = conn.execute("SELECT id, relation FROM edges").fetchall()
    updated = 0
    for row in rows:
        normalized = normalize_resume_relation(row["relation"])
        if normalized == row["relation"]:
            continue
        conn.execute("UPDATE edges SET relation = ? WHERE id = ?", (normalized, row["id"]))
        updated += 1
    if updated:
        conn.commit()
    return updated


def promote_resume_skill_nodes(
    conn: sqlite3.Connection,
    llm_client,
    source_ref: str,
    *,
    vector_store: VectorStore,
    config: JobctlConfig | None = None,
) -> dict[str, int]:
    """Promote nested resume technology properties into first-class skills."""
    nodes = search_nodes(conn)
    skill_lookup = {
        _normalize_skill_name(node["name"]): node for node in nodes if node["type"] == "skill"
    }
    created = 0
    edge_count = 0

    for node in nodes:
        if node["type"] not in _SKILL_CONTAINER_TYPES:
            continue
        for skill_name in _extract_skill_names(node.get("properties") or {}):
            normalized = _normalize_skill_name(skill_name)
            if not normalized:
                continue
            skill_node = skill_lookup.get(normalized)
            if skill_node is None:
                skill_id = add_node(
                    conn,
                    "skill",
                    skill_name,
                    {"source_context": f"Promoted from {node['type']}:{node['name']}"},
                    skill_name,
                )
                _index_node_best_effort(conn, vector_store, skill_id, llm_client, config=config)
                add_node_source(
                    conn,
                    skill_id,
                    "resume",
                    source_ref,
                    0.9,
                    f"{skill_name} mentioned in {node['name']}",
                )
                skill_node = get_node(conn, skill_id)
                skill_lookup[normalized] = skill_node
                created += 1
            else:
                _merge_skill_context(conn, skill_node["id"], node)
            if (
                add_edge_if_missing(conn, node["id"], skill_node["id"], "used_skill", {})
                is not None
            ):
                edge_count += 1

    return {"skills_created": created, "skill_edges_added": edge_count}


def _extract_skill_names(properties: dict[str, Any]) -> list[str]:
    names: list[str] = []
    for key, value in properties.items():
        normalized_key = str(key).casefold()
        if normalized_key not in _TECH_PROPERTY_KEYS:
            continue
        names.extend(_flatten_skill_values(value))
    return _dedupe_skill_names(names)


def _flatten_skill_values(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return _split_skill_text(value)
    if isinstance(value, list):
        names: list[str] = []
        for item in value:
            names.extend(_flatten_skill_values(item))
        return names
    if isinstance(value, dict):
        names: list[str] = []
        for item in value.values():
            names.extend(_flatten_skill_values(item))
        return names
    return []


def _split_skill_text(value: str) -> list[str]:
    text = value.strip()
    if not text:
        return []
    separators = [",", ";", " / "]
    parts = [text]
    for separator in separators:
        next_parts: list[str] = []
        for part in parts:
            next_parts.extend(part.split(separator))
        parts = next_parts
    return [_clean_skill_name(part) for part in parts if _clean_skill_name(part)]


def _clean_skill_name(value: str) -> str:
    return value.strip().strip(".:()[]{}")


def _dedupe_skill_names(names: list[str]) -> list[str]:
    deduped: dict[str, str] = {}
    for name in names:
        normalized = _normalize_skill_name(name)
        if normalized:
            deduped.setdefault(normalized, name)
    return list(deduped.values())


def _normalize_skill_name(value: str) -> str:
    return _normalize_text(value).replace(" ", "")


def _merge_skill_context(
    conn: sqlite3.Connection,
    skill_id: str,
    source_node: dict[str, Any],
) -> None:
    skill = get_node(conn, skill_id)
    contexts = list(skill.get("properties", {}).get("contexts") or [])
    context = f"{source_node['type']}:{source_node['name']}"
    if context in contexts:
        return
    properties = dict(skill.get("properties") or {})
    properties["contexts"] = [*contexts, context]
    update_node(conn, skill_id, properties=properties)


def _find_role_for_node(
    node: dict[str, Any],
    roles: list[dict[str, Any]],
    companies: list[dict[str, Any]],
    role_company: dict[str, str],
) -> dict[str, Any] | None:
    evidence = _node_evidence(node)
    company = _find_named_node(evidence, companies, allow_aliases=True)
    if company is not None:
        for role in roles:
            if role_company.get(role["id"]) == company["id"]:
                return role
    return _find_named_node(evidence, roles)


def _find_named_node(
    evidence: str,
    candidates: list[dict[str, Any]],
    *,
    allow_aliases: bool = False,
) -> dict[str, Any] | None:
    normalized = _normalize_text(evidence)
    matches = [
        candidate
        for candidate in candidates
        if any(
            alias and alias in normalized
            for alias in _candidate_aliases(candidate["name"], allow_aliases=allow_aliases)
        )
    ]
    if not matches:
        return None
    return max(matches, key=lambda candidate: len(candidate["name"]))


def _candidate_aliases(name: str, *, allow_aliases: bool) -> list[str]:
    normalized = _normalize_text(name)
    aliases = [normalized]
    if allow_aliases:
        for marker in (" of ", " - ", " | "):
            if marker in normalized:
                aliases.append(normalized.split(marker, 1)[1])
    return list(dict.fromkeys(aliases))


def _node_evidence(node: dict[str, Any]) -> str:
    properties = node.get("properties") or {}
    return " ".join(
        [
            str(node.get("name") or ""),
            str(node.get("text_representation") or ""),
            str(properties.get("source_context") or ""),
            str(properties.get("description") or ""),
        ]
    )


def _normalize_text(value: str) -> str:
    return " ".join(value.casefold().replace("–", "-").replace("—", "-").split())


def _first(nodes: list[dict[str, Any]]) -> dict[str, Any] | None:
    return nodes[0] if nodes else None


def _create_update_proposal(
    proposal_store: CurationProposalStore,
    item: FactReconciliation,
    source_ref: str,
) -> None:
    fact = item.source_fact
    node_id = item.matched_node_ids[0] if item.matched_node_ids else None
    current_text = item.candidate_matches[0].text if item.candidate_matches else ""
    proposal_store.create_proposal(
        "update_fact",
        {
            "source_type": "resume",
            "source_ref": source_ref,
            "node_id": node_id,
            "current_text": current_text,
            "proposed_text": fact.text_representation,
            "proposed_properties": fact.properties,
            "fact": fact.model_dump(),
            "confidence": item.confidence,
            "reason": item.reason,
            "requires_confirmation": item.requires_confirmation,
        },
    )


def _index_node_best_effort(
    conn: sqlite3.Connection,
    vector_store: VectorStore,
    node_id: str,
    llm_client,
    *,
    config: JobctlConfig | None = None,
) -> None:
    if llm_client is None or not hasattr(llm_client, "get_embedding"):
        return
    try:
        index_node(conn, vector_store, node_id, llm_client, config=config)
    except Exception as exc:  # noqa: BLE001 - embeddings should not block graph writes
        logger.warning("Skipping vector index for node %s: %s", node_id, exc)


def _publish_progress(
    bus: AsyncEventBus | None,
    job_id: str | None,
    current: int,
    total: int,
    message: str,
) -> None:
    if bus is None:
        return
    bus.publish(
        IngestProgressEvent(
            source="resume",
            current=current,
            total=total,
            message=message,
            job_id=job_id,
        )
    )


def _read_pdf(file_path: Path) -> str:
    try:
        import fitz
    except ModuleNotFoundError as exc:
        raise UnsupportedFormatError("PDF resume parsing requires pymupdf") from exc

    with fitz.open(file_path) as document:
        return "\n".join(page.get_text() for page in document)


def _read_docx(file_path: Path) -> str:
    try:
        import docx
    except ModuleNotFoundError as exc:
        raise UnsupportedFormatError("DOCX resume parsing requires python-docx") from exc

    document = docx.Document(file_path)
    return "\n".join(paragraph.text for paragraph in document.paragraphs if paragraph.text)


def _confirm_fact(fact: ExtractedFact) -> ExtractedFact | None:
    while True:
        console.print(_fact_panel(fact))
        choice = Prompt.ask("Persist this fact?", choices=["y", "n", "e"], default="y").lower()
        if choice == "y":
            return fact
        if choice == "n":
            return None
        edited_fact = _edit_fact(fact)
        if edited_fact is not None:
            fact = edited_fact


def _fact_panel(fact: ExtractedFact) -> Panel:
    fact_yaml = yaml.safe_dump(fact.model_dump(), sort_keys=False)
    return Panel(Syntax(fact_yaml, "yaml"), title=f"{fact.entity_type}: {fact.entity_name}")


def _edit_fact(fact: ExtractedFact) -> ExtractedFact | None:
    editor = os.environ.get("EDITOR")
    if not editor:
        console.print("Set $EDITOR to edit facts.")
        return None

    with tempfile.NamedTemporaryFile("w+", suffix=".yaml", delete=False) as temp_file:
        temp_path = Path(temp_file.name)
        temp_file.write(yaml.safe_dump(fact.model_dump(), sort_keys=False))

    try:
        subprocess.run([*shlex.split(editor), str(temp_path)], check=True)
        edited_data = yaml.safe_load(temp_path.read_text(encoding="utf-8"))
        return ExtractedFact.model_validate(edited_data)
    finally:
        temp_path.unlink(missing_ok=True)


def _resolve_related_node(
    conn: sqlite3.Connection,
    fact: ExtractedFact,
    llm_client,
    *,
    vector_store: VectorStore,
    config: JobctlConfig | None = None,
) -> str | None:
    if not fact.related_to:
        return None

    matches = search_nodes(conn, name_contains=fact.related_to)
    exact_matches = [node for node in matches if node["name"].lower() == fact.related_to.lower()]
    if exact_matches:
        return exact_matches[0]["id"]

    related_node_id = add_node(conn, "unknown", fact.related_to, {}, fact.related_to)
    _index_node_best_effort(conn, vector_store, related_node_id, llm_client, config=config)
    return related_node_id


def _edge_direction(
    conn: sqlite3.Connection,
    node_id: str,
    related_node_id: str,
    relation: str,
    entity_type: str,
) -> tuple[str, str]:
    if relation in {"used_skill", "achieved", "worked_at"} and entity_type != "role":
        related_type = conn.execute(
            "SELECT type FROM nodes WHERE id = ?",
            (related_node_id,),
        ).fetchone()["type"]
        if related_type == "role":
            return related_node_id, node_id
    return node_id, related_node_id
