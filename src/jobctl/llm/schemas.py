"""Pydantic schemas for structured LLM extraction."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ExtractedFact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entity_type: str
    entity_name: str
    relation: str | None
    related_to: str | None
    properties: dict[str, Any] = Field(default_factory=dict)
    text_representation: str

    @field_validator("properties", mode="before")
    @classmethod
    def _properties_from_key_value_pairs(cls, value: Any) -> Any:
        if isinstance(value, list):
            converted: dict[str, Any] = {}
            for item in value:
                if isinstance(item, dict) and "key" in item and "value" in item:
                    converted[str(item["key"])] = item["value"]
            return converted
        return value


class ExtractedProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    facts: list[ExtractedFact] = Field(default_factory=list)


class ExtractedJD(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    company: str
    location: str
    compensation: str | None = None
    requirements: list[str] = Field(default_factory=list)
    responsibilities: list[str] = Field(default_factory=list)
    qualifications: list[str] = Field(default_factory=list)
    nice_to_haves: list[str] = Field(default_factory=list)
    raw_text: str

    @field_validator("title", "company", "location", "raw_text", mode="before")
    @classmethod
    def _coerce_null_string(cls, value: Any) -> Any:
        if value is None:
            return ""
        return value

    @field_validator(
        "requirements",
        "responsibilities",
        "qualifications",
        "nice_to_haves",
        mode="before",
    )
    @classmethod
    def _coerce_null_list(cls, value: Any) -> Any:
        if value is None:
            return []
        return value


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


class ProposedFacts(BaseModel):
    model_config = ConfigDict(extra="forbid")

    facts: list[ProposedFact] = Field(default_factory=list)
