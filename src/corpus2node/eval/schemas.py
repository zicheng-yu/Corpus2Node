"""Eval contracts: a small gold dataset + per-capability metric reports."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from uuid import UUID

from pydantic import BaseModel, Field

from corpus2node.core.clock import utcnow


# ── gold dataset ──────────────────────────────────────────────────────────────


class GoldConcept(BaseModel):
    name: str
    aliases: list[str] = Field(default_factory=list)


class GoldRelation(BaseModel):
    source: str
    target: str
    relation_type: str = ""


class GoldDataset(BaseModel):
    name: str = ""
    concepts: list[GoldConcept] = Field(default_factory=list)
    relations: list[GoldRelation] = Field(default_factory=list)
    qa_questions: list[str] = Field(default_factory=list)


def load_gold(path: str | Path) -> GoldDataset:
    return GoldDataset.model_validate(json.loads(Path(path).read_text(encoding="utf-8")))


def default_gold() -> GoldDataset:
    """The packaged gold set for tests/fixtures/sample_lecture.md."""
    return load_gold(Path(__file__).parent / "data" / "sample_lecture.gold.json")


# ── metric reports ────────────────────────────────────────────────────────────


class ExtractionEval(BaseModel):
    predicted_concepts: int = 0
    gold_concepts: int = 0
    matched_predicted: int = 0
    matched_gold: int = 0
    concept_precision: float = 0.0
    concept_recall: float = 0.0
    concept_f1: float = 0.0
    edges: int = 0
    relation_validity_rate: float = 0.0
    relation_recall: float = 0.0


class NotesEval(BaseModel):
    core_concepts: int = 0
    covered: int = 0
    coverage: float = 0.0
    sections: int = 0


class ExamEval(BaseModel):
    questions: int = 0
    traceable: int = 0
    traceability: float = 0.0
    objective: int = 0
    objective_valid: int = 0
    objective_validity: float = 0.0


class QAEval(BaseModel):
    questions: int = 0
    answered: int = 0
    grounded: int = 0
    groundedness: float = 0.0
    chunk_grounded: int = 0
    avg_citations: float = 0.0
    answer_key_agreement: float | None = None  # exam-solver agreement (LLM run only)


class EvalReport(BaseModel):
    session_id: UUID
    generated_at: datetime = Field(default_factory=utcnow)
    extraction: ExtractionEval | None = None
    notes: NotesEval | None = None
    exam: ExamEval | None = None
    qa: QAEval | None = None
