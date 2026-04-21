"""Typed contracts for enriched resume ingestion."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from jobctl.llm.schemas import ExtractedFact


ReconciliationClassification = Literal["duplicate", "update", "new", "ambiguous", "conflict"]


class NodeMatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id: str
    node_type: str
    name: str
    text: str
    score: float = 0.0
    confidence: float = 0.0
    signals: list[str] = Field(default_factory=list)


class FactReconciliation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_fact: ExtractedFact
    classification: ReconciliationClassification
    confidence: float = 0.0
    matched_node_ids: list[str] = Field(default_factory=list)
    candidate_matches: list[NodeMatch] = Field(default_factory=list)
    reason: str = ""
    proposed_action: str = ""
    requires_confirmation: bool = False


class ResumeReconciliationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_ref: str
    facts: list[FactReconciliation] = Field(default_factory=list)
    summary_counts: dict[str, int] = Field(default_factory=dict)


class PositioningOpportunity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: str
    current_evidence: str = ""
    suggested_positioning: str = ""
    confirmation_required: bool = True
    risk_level: Literal["low", "medium", "high"] = "medium"
    reason: str = ""


class RefinementQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str | None = None
    source_type: str = "resume"
    source_ref: str = ""
    target_node_id: str | None = None
    fact: ExtractedFact | None = None
    category: str
    prompt: str
    options: list[str] = Field(default_factory=list)
    allow_free_text: bool = True
    status: Literal["pending", "answered", "skipped", "dismissed", "converted_to_update"] = (
        "pending"
    )
    answer_text: str | None = None
    answer_json: dict[str, Any] | None = None
    priority: int = 0
    raw_evidence: str = ""
    positioning_opportunity: PositioningOpportunity | None = None
    created_at: str | None = None
    answered_at: str | None = None


class GraphUpdatePlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question_id: str | None = None
    source_ref: str = ""
    target_node_id: str | None = None
    node_updates: dict[str, Any] = Field(default_factory=dict)
    new_facts: list[ExtractedFact] = Field(default_factory=list)
    new_edges: list[dict[str, Any]] = Field(default_factory=list)
    source_evidence: list[dict[str, Any]] = Field(default_factory=list)
    resume_ready_phrasing: str | None = None
    positioning_confirmation_status: Literal["not_applicable", "confirmed", "needs_review"] = (
        "not_applicable"
    )
    requires_review: bool = False
    reason: str = ""


__all__ = [
    "FactReconciliation",
    "GraphUpdatePlan",
    "NodeMatch",
    "PositioningOpportunity",
    "RefinementQuestion",
    "ReconciliationClassification",
    "ResumeReconciliationResult",
]
