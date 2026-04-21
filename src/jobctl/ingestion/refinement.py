"""Plan resume refinement questions from reconciliation output."""

from __future__ import annotations

import sqlite3
from typing import Any

from jobctl.ingestion.questions import RefinementQuestionStore
from jobctl.ingestion.schemas import RefinementQuestion, ResumeReconciliationResult


_CATEGORIES = (
    (
        "metrics",
        "What measurable result, scale, or before/after impact can you confirm for this experience?",
    ),
    ("ownership", "What part of this work did you personally own, decide, or drive?"),
    (
        "technical_leadership",
        "Did you guide technical direction, mentor others, or lead implementation decisions for this work?",
    ),
    (
        "production_ownership",
        "What production reliability, rollout, or operational responsibility did this work involve?",
    ),
)


def plan_refinement_questions(
    conn: sqlite3.Connection,
    reconciliation: ResumeReconciliationResult,
    llm_client: Any,
    max_questions: int = 5,
) -> list[RefinementQuestion]:
    """Generate a capped set of high-value questions.

    The implementation uses deterministic gaps first and lets callers add an LLM
    planner later without changing storage contracts.
    """
    del conn, llm_client
    questions: list[RefinementQuestion] = []
    for item in reconciliation.facts:
        if item.classification not in {"new", "update"}:
            continue
        fact = item.source_fact
        text = f"{fact.entity_name} {fact.text_representation}".casefold()
        missing_metric = not any(char.isdigit() for char in text)
        missing_owner = not any(
            marker in text
            for marker in ("led", "owned", "architected", "designed", "mentored", "drove")
        )
        category_prompts = []
        if missing_metric:
            category_prompts.append(_CATEGORIES[0])
        if missing_owner:
            category_prompts.append(_CATEGORIES[1])
        if fact.entity_type.casefold() in {"role", "achievement", "project"}:
            category_prompts.append(_CATEGORIES[2])
        for category, prompt in category_prompts:
            if len(questions) >= max_questions:
                return questions
            target_node_id = item.matched_node_ids[0] if item.matched_node_ids else None
            questions.append(
                RefinementQuestion(
                    source_type="resume",
                    source_ref=reconciliation.source_ref,
                    target_node_id=target_node_id,
                    fact=fact,
                    category=category,
                    prompt=f"{prompt}\n\nExperience: {fact.text_representation}",
                    options=[],
                    allow_free_text=True,
                    priority=_priority_for(category),
                    raw_evidence=fact.text_representation,
                )
            )
    return questions[:max_questions]


def persist_refinement_questions(
    store: RefinementQuestionStore,
    questions: list[RefinementQuestion],
) -> list[str]:
    return store.create_many(questions)


def _priority_for(category: str) -> int:
    return {"metrics": 100, "ownership": 90, "technical_leadership": 80}.get(category, 50)


__all__ = ["persist_refinement_questions", "plan_refinement_questions"]
