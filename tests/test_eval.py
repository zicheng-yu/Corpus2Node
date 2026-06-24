from __future__ import annotations

import uuid
from types import SimpleNamespace

from corpus2node.core.types import (
    ChatCitation,
    ExamChoice,
    ExamDocument,
    ExamQuestion,
    NoteDocument,
    NoteSection,
)
from corpus2node.eval import metrics
from corpus2node.eval.harness import evaluate_exam, evaluate_extraction, evaluate_notes, evaluate_qa
from corpus2node.eval.schemas import default_gold
from corpus2node.graph.build import build_graph_artifact
from corpus2node.graph.schemas import ExtractedConcept, ExtractedRelation, GraphExtractionResult
from corpus2node.index.embeddings import HashingEmbeddings

EMB = HashingEmbeddings(dims=128)


def _graph():
    chunks = []
    candidates = GraphExtractionResult(
        concepts=[
            ExtractedConcept(name="二叉搜索树", canonical_name="二叉搜索树", definition="用于查找的树", aliases=["BST"]),
            ExtractedConcept(name="平衡树", canonical_name="平衡树", definition="二叉搜索树的改进"),
            ExtractedConcept(name="树结构", canonical_name="树结构", definition="层次数据结构"),
        ],
        relations=[
            ExtractedRelation(source_canonical_name="二叉搜索树", target_canonical_name="树结构", edge_type="RELATES_TO", relation_type="is_a"),
            ExtractedRelation(source_canonical_name="平衡树", target_canonical_name="二叉搜索树", edge_type="RELATES_TO", relation_type="is_a"),
        ],
    )
    return build_graph_artifact(uuid.uuid4(), chunks, candidates, embeddings=EMB)


def test_concept_prf_is_alias_aware():
    pred = [metrics.keys("BST", "二叉搜索树")]
    gold = [metrics.keys("二叉查找树", "BST")]  # overlaps on BST
    precision, recall, f1, mp, mg = metrics.concept_prf(pred, gold)
    assert precision == 1.0 and recall == 1.0 and f1 == 1.0 and mp == 1 and mg == 1


def test_evaluate_extraction_against_default_gold():
    report = evaluate_extraction(_graph(), default_gold())
    assert report.gold_concepts == 3
    assert report.concept_recall == 1.0  # all three gold concepts present
    assert report.concept_f1 > 0.9
    assert report.relation_validity_rate == 1.0  # all RELATES_TO edges carry a valid relation_type
    assert report.relation_recall == 1.0  # both gold is_a relations found


def test_evaluate_notes_coverage():
    graph = _graph()
    covered = [graph.concepts[0].concept_id, graph.concepts[1].concept_id]
    note = NoteDocument(
        session_id=graph.session_id, title="T", topic="t", summary="s",
        sections=[NoteSection(title="S1", content_md="x", concept_ids=covered)],
    )
    report = evaluate_notes(note, graph)
    assert report.core_concepts == len(graph.concepts)
    assert report.covered == 2
    assert 0 < report.coverage <= 1.0


def test_evaluate_exam_traceability_and_objective_validity():
    exam = ExamDocument(
        session_id=uuid.uuid4(), title="E", summary="s",
        questions=[
            ExamQuestion(
                question_type="single_choice", stem="Q1?",
                choices=[ExamChoice(choice_id=c, text="x") for c in "ABCD"],
                answer="B", explanation="e", concept_ids=["concept:1"],
            ),
            ExamQuestion(
                question_type="single_choice", stem="Q2?",
                choices=[ExamChoice(choice_id=c, text="x") for c in "ABCD"],
                answer="Z", explanation="e", concept_ids=[],  # invalid answer + untraceable
            ),
        ],
    )
    report = evaluate_exam(exam)
    assert report.questions == 2
    assert report.traceable == 1 and report.traceability == 0.5
    assert report.objective == 2 and report.objective_valid == 1 and report.objective_validity == 0.5


def test_evaluate_qa_groundedness():
    turns = [
        SimpleNamespace(answer="答案 [1]", citations=[ChatCitation(index=1, kind="chunk", ref_id="c1")]),
        SimpleNamespace(answer="仅概念 [1]", citations=[ChatCitation(index=1, kind="concept", ref_id="k1")]),
        SimpleNamespace(answer="无依据", citations=[]),
    ]
    report = evaluate_qa(turns)
    assert report.questions == 3
    assert report.grounded == 2 and report.groundedness == round(2 / 3, 3)
    assert report.chunk_grounded == 1
    assert report.answered == 3


def test_default_gold_loads():
    gold = default_gold()
    assert {c.name for c in gold.concepts} == {"树结构", "二叉搜索树", "平衡树"}
    assert len(gold.relations) == 2
