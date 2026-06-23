"""Structured-output schemas for note generation (via with_structured_output)."""
from __future__ import annotations

from pydantic import BaseModel, Field


class LLMNoteSection(BaseModel):
    title: str = ""
    content_md: str = ""
    concept_ids: list[str] = Field(default_factory=list)


class LLMNoteSummary(BaseModel):
    summary: str = ""
