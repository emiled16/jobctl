"""Pydantic schemas for generated application materials."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ContactInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    email: str
    phone: str | None = None
    location: str | None = None
    linkedin: str | None = None
    github: str | None = None
    website: str | None = None


class ExperienceEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    company: str
    title: str
    start_date: str
    end_date: str | None = None
    bullets: list[str] = Field(default_factory=list)


class EducationEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    institution: str
    degree: str
    field: str | None = None
    end_date: str | None = None
    details: list[str] | None = None


class ResumeYAML(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contact: ContactInfo
    summary: str
    experience: list[ExperienceEntry] = Field(default_factory=list)
    skills: dict[str, list[str]] = Field(default_factory=dict)
    education: list[EducationEntry] = Field(default_factory=list)
    certifications: list[str] | None = None
    projects: list[dict[str, Any]] | None = None


class CoverLetterYAML(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recipient: str | None = None
    company: str
    role: str
    opening: str
    body_paragraphs: list[str] = Field(default_factory=list)
    closing: str
