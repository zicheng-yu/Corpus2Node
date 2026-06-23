"""Structured-output schemas for exam generation + verification."""
from __future__ import annotations

from pydantic import BaseModel, Field


class LLMExamChoice(BaseModel):
    choice_id: str = ""
    text: str = ""


class LLMExamQuestion(BaseModel):
    question_type: str = ""
    stem: str = ""
    choices: list[LLMExamChoice] = Field(default_factory=list)
    answer: str = ""
    explanation: str = ""
    difficulty: str = "medium"
    concept_ids: list[str] = Field(default_factory=list)
    tested_points: list[str] = Field(default_factory=list)
    importance_basis: str = ""


class LLMExamDocument(BaseModel):
    title: str = ""
    summary: str = ""
    questions: list[LLMExamQuestion] = Field(default_factory=list)


class SolvedAnswer(BaseModel):
    """The verifier's independent answer to one question, grounded in the graph/原文."""

    answer: str = ""
    grounded: bool = False
    reasoning: str = ""
