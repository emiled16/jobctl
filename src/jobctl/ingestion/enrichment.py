"""Convert answered refinement questions into graph update plans."""

from __future__ import annotations

import sqlite3
import json
import logging
from difflib import unified_diff
from typing import Any

from jobctl.curation.proposals import CurationProposalStore
from jobctl.db.graph import add_node_source, get_node, merge_node_properties, update_node
from jobctl.db.vectors import embed_node
from jobctl.ingestion.resume import persist_reconciled_resume_facts
from jobctl.ingestion.schemas import GraphUpdatePlan, RefinementQuestion, ResumeReconciliationResult

logger = logging.getLogger(__name__)


def build_graph_update_from_answer(
    question: RefinementQuestion,
    answer: str,
    llm_client: Any,
) -> GraphUpdatePlan:
    if llm_client is not None and hasattr(llm_client, "chat_structured"):
        messages = [
            {
                "role": "system",
                "content": (
                    "Convert the user's answer into a conservative graph update plan. "
                    "Separate confirmed facts from resume-ready phrasing. Do not invent "
                    "titles, metrics, team sizes, responsibilities, or stronger positioning."
                ),
            },
            {
                "role": "user",
                "content": json.dumps({"question": question.model_dump(), "answer": answer}),
            },
        ]
        try:
            plan = llm_client.chat_structured(messages, response_format=GraphUpdatePlan)
            plan.question_id = question.id
            plan.source_ref = question.source_ref
            if _plan_has_changes(plan):
                return plan
        except Exception:
            pass
    updates = {"refinement_notes": [answer]}
    if question.category == "metrics":
        updates["confirmed_impact"] = answer
    return GraphUpdatePlan(
        question_id=question.id,
        source_ref=question.source_ref,
        target_node_id=question.target_node_id,
        node_updates=updates,
        source_evidence=[{"quote": answer, "source_type": question.source_type}],
        resume_ready_phrasing=answer,
        positioning_confirmation_status="needs_review"
        if question.category == "technical_leadership"
        else "not_applicable",
        requires_review=question.category == "technical_leadership",
        reason="Derived from answered refinement question.",
    )


def apply_graph_update_plan(
    conn: sqlite3.Connection,
    plan: GraphUpdatePlan,
    llm_client: Any,
    source_ref: str,
) -> dict[str, int]:
    if plan.requires_review:
        CurationProposalStore(conn).create_proposal("refine_experience", plan.model_dump())
        return {"nodes_updated": 0, "facts_added": 0, "proposals_created": 1}

    updated = 0
    if plan.target_node_id and plan.node_updates:
        node = get_node(conn, plan.target_node_id)
        merged = merge_node_properties(node.get("properties"), plan.node_updates)
        update_fields: dict[str, Any] = {"properties": merged}
        if plan.resume_ready_phrasing:
            update_fields["text_representation"] = _append_once(
                node["text_representation"], plan.resume_ready_phrasing
            )
        update_node(conn, plan.target_node_id, **update_fields)
        add_node_source(
            conn,
            plan.target_node_id,
            "resume_refinement",
            source_ref,
            1.0,
            plan.resume_ready_phrasing,
        )
        if llm_client is not None and hasattr(llm_client, "get_embedding"):
            try:
                embed_node(conn, plan.target_node_id, llm_client)
            except Exception as exc:  # noqa: BLE001 - graph update already succeeded
                logger.warning(
                    "Skipping refinement embedding for node %s: %s", plan.target_node_id, exc
                )
        updated += 1

    facts_added = 0
    if plan.new_facts:
        reconciliation = ResumeReconciliationResult(
            source_ref=source_ref,
            facts=[
                {
                    "source_fact": fact,
                    "classification": "new",
                    "confidence": 1.0,
                    "reason": "Confirmed refinement answer.",
                    "proposed_action": "add_fact",
                    "requires_confirmation": False,
                }
                for fact in plan.new_facts
            ],
        )
        facts_added = persist_reconciled_resume_facts(
            conn, reconciliation, llm_client, source_ref
        ).get("added", 0)
    return {"nodes_updated": updated, "facts_added": facts_added, "proposals_created": 0}


def preview_graph_update_plan(conn: sqlite3.Connection, plan: GraphUpdatePlan) -> str:
    """Render a Markdown diff preview for a graph update plan."""
    sections: list[str] = []
    if plan.target_node_id and plan.node_updates:
        node = get_node(conn, plan.target_node_id)
        merged = merge_node_properties(node.get("properties"), plan.node_updates)
        sections.append(
            _unified_diff_block(
                f"{node['type']}:{node['name']} properties",
                _json_lines(node.get("properties") or {}),
                _json_lines(merged),
            )
        )
        if plan.resume_ready_phrasing:
            before_text = node["text_representation"]
            after_text = _append_once(before_text, plan.resume_ready_phrasing)
            if after_text != before_text:
                sections.append(
                    _unified_diff_block(
                        f"{node['type']}:{node['name']} text",
                        before_text.splitlines(),
                        after_text.splitlines(),
                    )
                )

    for fact in plan.new_facts:
        sections.append(
            _unified_diff_block(
                f"new {fact.entity_type}:{fact.entity_name}",
                [],
                _json_lines(fact.model_dump()),
            )
        )

    for edge in plan.new_edges:
        sections.append(_unified_diff_block("new edge", [], _json_lines(edge)))

    if plan.requires_review:
        sections.append(
            "This update requires review. Accepting will create a Curate proposal instead "
            "of mutating the graph directly."
        )

    if plan.reason:
        sections.append(f"Reason: {plan.reason}")
    if not sections:
        sections.append("No direct graph changes were generated from this answer.")
    return "\n\n".join(sections)


def _unified_diff_block(label: str, before: list[str], after: list[str]) -> str:
    diff = "\n".join(
        unified_diff(
            before,
            after,
            fromfile=f"a/{label}",
            tofile=f"b/{label}",
            lineterm="",
        )
    )
    return f"```diff\n{diff}\n```"


def _json_lines(value: dict[str, Any]) -> list[str]:
    return json.dumps(value, indent=2, sort_keys=True, default=str).splitlines()


def _append_once(existing: str, addition: str) -> str:
    if not addition or addition in existing:
        return existing
    return f"{existing}\n{addition}"


def _plan_has_changes(plan: GraphUpdatePlan) -> bool:
    return bool(
        plan.node_updates
        or plan.new_facts
        or plan.new_edges
        or plan.source_evidence
        or plan.resume_ready_phrasing
        or plan.requires_review
    )


__all__ = [
    "apply_graph_update_plan",
    "build_graph_update_from_answer",
    "preview_graph_update_plan",
]
