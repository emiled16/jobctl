"""Pydantic schemas for generated application materials."""

from typing import Literal

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


class ProjectEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    description: str
    url: str | None = None
    bullets: list[str] | None = None


class PublicationEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    publisher: str | None = None
    date: str | None = None
    url: str | None = None
    description: str | None = None


class ResumeSectionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    title: str | None = None
    order: int | None = None


class ResumeRenderOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    template: str | None = None
    sections: dict[str, ResumeSectionConfig] = Field(default_factory=dict)


class ResumeYAML(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_type: Literal["resume"] | None = None
    schema_version: int | None = None
    render: ResumeRenderOptions | None = None
    contact: ContactInfo
    summary: str
    experience: list[ExperienceEntry] = Field(default_factory=list)
    skills: dict[str, list[str]] = Field(default_factory=dict)
    education: list[EducationEntry] = Field(default_factory=list)
    certifications: list[str] | None = None
    projects: list[ProjectEntry] | None = None
    publications: list[PublicationEntry] | None = None


class CoverLetterYAML(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_type: Literal["cover_letter"] | Literal["cover-letter"] | None = None
    schema_version: int | None = None
    recipient: str | None = None
    company: str
    role: str
    opening: str
    body_paragraphs: list[str] = Field(default_factory=list)
    closing: str
