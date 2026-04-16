"""Pydantic schemas for structured LLM extraction."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ExtractedFact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entity_type: str
    entity_name: str
    relation: str | None
    related_to: str | None
    properties: dict[str, Any] = Field(default_factory=dict)
    text_representation: str


class ExtractedProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    facts: list[ExtractedFact] = Field(default_factory=list)


class ExtractedJD(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    company: str
    location: str
    compensation: str | None
    requirements: list[str] = Field(default_factory=list)
    responsibilities: list[str] = Field(default_factory=list)
    qualifications: list[str] = Field(default_factory=list)
    nice_to_haves: list[str] = Field(default_factory=list)
    raw_text: str


class FitEvaluation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    score: float
    matching_strengths: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    summary: str


class ProposedFact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fact: ExtractedFact
    confidence: float
    source_quote: str
