"""Pure metric functions for the eval harness (no IO, no LLM)."""
from __future__ import annotations

import re

from corpus2node.core.text import canonicalize_term
from corpus2node.core.types import ConceptNode, EdgeType, ExamQuestion, GraphEdge
from corpus2node.graph.clean import VALID_RELATION_TYPES


def keys(*names: str) -> set[str]:
    """Canonicalized identity keys for alias-aware matching."""
    return {canonicalize_term(name) for name in names if name and canonicalize_term(name)}


def concept_prf(pred_keysets: list[set[str]], gold_keysets: list[set[str]]) -> tuple[float, float, float, int, int]:
    """Alias-aware concept precision/recall/F1. A pair matches if their key sets intersect."""
    matched_gold = sum(1 for gold in gold_keysets if any(gold & pred for pred in pred_keysets))
    matched_pred = sum(1 for pred in pred_keysets if any(gold & pred for gold in gold_keysets))
    precision = matched_pred / len(pred_keysets) if pred_keysets else 0.0
    recall = matched_gold / len(gold_keysets) if gold_keysets else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return precision, recall, f1, matched_pred, matched_gold


def edge_type_value(edge: GraphEdge) -> str:
    return edge.edge_type.value if hasattr(edge.edge_type, "value") else str(edge.edge_type)


def relation_validity_rate(edges: list[GraphEdge]) -> float:
    """Of the semantic (RELATES_TO) edges, the fraction carrying a valid relation_type."""
    semantic = [edge for edge in edges if edge_type_value(edge) == EdgeType.relates_to.value]
    if not semantic:
        return 1.0  # no semantic relations → nothing invalid
    ok = sum(1 for edge in semantic if edge.properties.get("relation_type") in VALID_RELATION_TYPES)
    return ok / len(semantic)


def objective_answer_valid(question: ExamQuestion) -> bool:
    """Is the answer key structurally valid for an objective question type?"""
    choice_ids = {choice.choice_id.upper() for choice in question.choices}
    if question.question_type == "single_choice":
        letters = set(re.findall(r"[A-D]", question.answer.upper()))
        return len(letters) == 1 and letters <= choice_ids
    if question.question_type == "multiple_choice":
        letters = set(re.findall(r"[A-D]", question.answer.upper()))
        return len(letters) >= 1 and letters <= choice_ids
    if question.question_type == "true_false":
        return any(token in question.answer for token in ("正确", "对", "错误", "错")) or question.answer.strip().lower() in {"true", "false"}
    if question.question_type == "fill_blank":
        return bool(question.answer.strip())
    return False


def core_concepts(concepts: list[ConceptNode], course_core_ids: set[str] | None, *, limit: int = 15) -> list[ConceptNode]:
    if course_core_ids:
        return [concept for concept in concepts if concept.concept_id in course_core_ids]
    return sorted(concepts, key=lambda concept: concept.importance_score, reverse=True)[:limit]
