from __future__ import annotations

import asyncio

from corpus2node.core.types import EvidenceChunk, SourceKind
from corpus2node.graph.critic import apply_repair, critique_candidates
from corpus2node.graph.schemas import (
    ConceptVerdict,
    ExtractedConcept,
    ExtractedRelation,
    GraphCriticReport,
    RelationVerdict,
)
from corpus2node.index.embeddings import HashingEmbeddings

EMB = HashingEmbeddings(dims=128)


def _candidates() -> "object":
    from corpus2node.graph.schemas import GraphExtractionResult

    return GraphExtractionResult(
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


def test_apply_repair_drops_ungrounded_concept_and_its_relations():
    report = GraphCriticReport(concept_verdicts=[ConceptVerdict(canonical_name="树结构", grounded=False)])
    repaired, stats = apply_repair(_candidates(), report)
    assert "树结构" not in {c.canonical_name for c in repaired.concepts}
    assert stats.dropped_concepts == 1
    assert all(r.target_canonical_name != "树结构" for r in repaired.relations)
    assert stats.dropped_relations >= 1


def test_apply_repair_flips_and_retypes_relation():
    report = GraphCriticReport(
        relation_verdicts=[
            RelationVerdict(source_canonical_name="平衡树", target_canonical_name="二叉搜索树", flip=True, corrected_relation_type="prerequisite_of"),
        ]
    )
    repaired, stats = apply_repair(_candidates(), report)
    relation = next(r for r in repaired.relations if {r.source_canonical_name, r.target_canonical_name} == {"平衡树", "二叉搜索树"})
    assert relation.source_canonical_name == "二叉搜索树" and relation.target_canonical_name == "平衡树"
    assert relation.relation_type == "prerequisite_of"
    assert stats.flipped_relations == 1 and stats.retyped_relations == 1


def test_apply_repair_merges_duplicate_concept():
    report = GraphCriticReport(concept_verdicts=[ConceptVerdict(canonical_name="平衡树", duplicate_of="二叉搜索树")])
    repaired, stats = apply_repair(_candidates(), report)
    names = {c.canonical_name for c in repaired.concepts}
    assert "平衡树" not in names and "二叉搜索树" in names
    assert stats.merged_concepts == 1
    bst = next(c for c in repaired.concepts if c.canonical_name == "二叉搜索树")
    assert "平衡树" in bst.aliases  # folded alias
    # 平衡树->二叉搜索树 collapses to a self-loop and is dropped; the other relation survives
    assert any(r.source_canonical_name == "二叉搜索树" and r.target_canonical_name == "树结构" for r in repaired.relations)


def test_apply_repair_empty_guard_keeps_everything():
    cands = _candidates()
    report = GraphCriticReport(concept_verdicts=[ConceptVerdict(canonical_name=c.canonical_name, grounded=False) for c in cands.concepts])
    repaired, stats = apply_repair(cands, report)
    assert len(repaired.concepts) == len(cands.concepts)  # never wipe the whole graph
    assert stats.total == 0


def test_invalid_corrected_relation_type_is_ignored():
    report = GraphCriticReport(
        relation_verdicts=[RelationVerdict(source_canonical_name="二叉搜索树", target_canonical_name="树结构", corrected_relation_type="nonsense")]
    )
    repaired, stats = apply_repair(_candidates(), report)
    relation = next(r for r in repaired.relations if r.target_canonical_name == "树结构")
    assert relation.relation_type == "is_a"  # unchanged — invalid type rejected
    assert stats.retyped_relations == 0


def test_critique_candidates_merges_concept_and_relation_verdicts():
    chunks = [
        EvidenceChunk(
            chunk_id="c0", source_id="s", source_type=SourceKind.pdf,
            text="二叉搜索树 用于 高效 查找", summary="", embedding=EMB.embed_query("二叉搜索树 查找"),
        )
    ]

    async def fake_acritic(prompt: str) -> GraphCriticReport:
        if "审查下列概念" in prompt:
            return GraphCriticReport(concept_verdicts=[ConceptVerdict(canonical_name="树结构", grounded=False)])
        return GraphCriticReport(
            relation_verdicts=[RelationVerdict(source_canonical_name="平衡树", target_canonical_name="二叉搜索树", flip=True)]
        )

    report = asyncio.run(critique_candidates(_candidates(), chunks, EMB, acritic=fake_acritic))
    assert any(v.canonical_name == "树结构" and not v.grounded for v in report.concept_verdicts)
    assert any(v.flip for v in report.relation_verdicts)
