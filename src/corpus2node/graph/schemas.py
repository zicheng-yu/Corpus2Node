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


# ── Graph critic (LLM-judge quality gate) ─────────────────────────────────────


class ConceptVerdict(BaseModel):
    canonical_name: str
    grounded: bool = True  # is the definition supported by the source chunks?
    duplicate_of: str = ""  # canonical_name of the concept this duplicates (empty = none)
    issue: str = ""


class RelationVerdict(BaseModel):
    source_canonical_name: str
    target_canonical_name: str
    keep: bool = True
    flip: bool = False  # source/target are reversed
    corrected_relation_type: str = ""  # empty = keep the original relation_type
    issue: str = ""


class GraphCriticReport(BaseModel):
    concept_verdicts: list[ConceptVerdict] = Field(default_factory=list)
    relation_verdicts: list[RelationVerdict] = Field(default_factory=list)
