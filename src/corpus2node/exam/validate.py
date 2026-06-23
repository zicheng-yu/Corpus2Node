"""Deterministic exam validation (ported from donor exam.py) + answer-matching for the verifier.

`coerce_question` is the donor's per-question validation lifted out of its loop so the
generator can *count* valid questions and top up — instead of the donor's silent
`continue` + final `[:n]` slice that returned fewer questions than requested.

`answers_match` ports the frontend grading rules to Python so the verifier (an
independent solver) can decide whether its answer agrees with the question's key.
"""
from __future__ import annotations

import re

from corpus2node.core.text import normalize_text
from corpus2node.core.types import ExamChoice, ExamQuestion
from corpus2node.exam.schemas import LLMExamQuestion

CHOICE_TYPES = {"single_choice", "multiple_choice"}
OBJECTIVE_TYPES = {"single_choice", "multiple_choice", "true_false", "fill_blank"}
ALL_TYPES = ["single_choice", "multiple_choice", "true_false", "fill_blank", "short_answer", "essay"]

_TYPE_ALIASES = {
    "single": "single_choice", "single_choice": "single_choice", "choice": "single_choice",
    "单选": "single_choice", "单选题": "single_choice",
    "multiple": "multiple_choice", "multiple_choice": "multiple_choice", "多选": "multiple_choice", "多选题": "multiple_choice",
    "true_false": "true_false", "判断": "true_false", "判断题": "true_false",
    "fill": "fill_blank", "fill_blank": "fill_blank", "blank": "fill_blank", "填空": "fill_blank", "填空题": "fill_blank",
    "short": "short_answer", "short_answer": "short_answer", "简答": "short_answer", "简答题": "short_answer",
    "essay": "essay", "论述": "essay", "论述题": "essay",
}


def normalize_question_type(value: str) -> str:
    return _TYPE_ALIASES.get(normalize_text(value).lower(), "short_answer")


def normalize_question_types(values: list[str]) -> list[str]:
    deduped = list(dict.fromkeys(normalize_question_type(value) for value in values))
    return deduped or list(ALL_TYPES)


def normalize_difficulty(value: str) -> str:
    normalized = normalize_text(value).lower()
    if normalized in {"easy", "简单", "low"}:
        return "easy"
    if normalized in {"hard", "困难", "高"}:
        return "hard"
    return "medium"


def coerce_question(
    question: LLMExamQuestion, *, valid_concept_ids: set[str], allowed_types: list[str]
) -> ExamQuestion | None:
    """Validate one LLM question into an ExamQuestion, or None if it can't be used."""
    stem = normalize_text(question.stem)
    answer = normalize_text(question.answer)
    explanation = normalize_text(question.explanation)
    if not stem or not answer or not explanation:
        return None

    question_type = normalize_question_type(question.question_type)
    if question_type not in allowed_types:
        return None

    concept_ids = [cid for cid in question.concept_ids if cid in valid_concept_ids]
    if not concept_ids:
        return None

    choices = [
        ExamChoice(choice_id=normalize_text(choice.choice_id).upper(), text=normalize_text(choice.text))
        for choice in question.choices
        if normalize_text(choice.choice_id) and normalize_text(choice.text)
    ]
    if question_type in CHOICE_TYPES:
        if len(choices) < 4:
            return None
        choices = choices[:4]

    return ExamQuestion(
        question_type=question_type,
        stem=stem,
        choices=choices,
        answer=answer,
        explanation=explanation,
        difficulty=normalize_difficulty(question.difficulty),
        concept_ids=concept_ids,
        tested_points=[normalize_text(point) for point in question.tested_points if normalize_text(point)],
        importance_basis=normalize_text(question.importance_basis),
    )


def answers_match(question_type: str, candidate: str, reference: str) -> bool | None:
    """Do two answers agree? None for subjective types that can't be graded objectively."""
    if question_type == "single_choice":
        return _choice_set(candidate) == _choice_set(reference) and bool(_choice_set(reference))
    if question_type == "multiple_choice":
        return _choice_set(candidate) == _choice_set(reference) and bool(_choice_set(reference))
    if question_type == "true_false":
        ref = _true_false(reference)
        return ref != "" and _true_false(candidate) == ref
    if question_type == "fill_blank":
        cand = _fill(candidate)
        return bool(cand) and any(_fill(alt) == cand for alt in _split_fill(reference))
    return None


def _choice_set(answer: str) -> str:
    return "".join(sorted(set(re.findall(r"[A-D]", answer.upper()))))


def _true_false(value: str) -> str:
    normalized = value.strip().lower()
    if any(token in normalized for token in ("正确", "对", "true", "yes", "√")):
        return "true"
    if any(token in normalized for token in ("错误", "错", "false", "no", "×")):
        return "false"
    return ""


def _split_fill(answer: str) -> list[str]:
    return [item.strip() for item in re.split(r"；|;|\||或", answer) if item.strip()]


def _fill(value: str) -> str:
    return re.sub(r"[\s，,。.;；:：、（）()《》<>“”\"']", "", value.strip().lower())
