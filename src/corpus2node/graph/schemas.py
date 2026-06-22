"""Structured-output schemas for LLM graph extraction (returned via with_structured_output)."""
from __future__ import annotations

from pydantic import BaseModel, Field

from corpus2node.core.types import EdgeType


class ExtractedConcept(BaseModel):
    name: str
    canonical_name: str = ""
    aliases: list[str] = Field(default_factory=list)
    definition: str = ""
    summary: str = ""
    key_points: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    prerequisites: list[str] = Field(default_factory=list)
    applications: list[str] = Field(default_factory=list)


class ExtractedRelation(BaseModel):
    source_canonical_name: str
    target_canonical_name: str
    edge_type: str = EdgeType.relates_to.value
    relation_type: str | None = None
    confidence: float = 0.72


class GraphExtractionResult(BaseModel):
    concepts: list[ExtractedConcept] = Field(default_factory=list)
    relations: list[ExtractedRelation] = Field(default_factory=list)
