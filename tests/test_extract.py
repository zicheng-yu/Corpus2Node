from __future__ import annotations

import asyncio

from corpus2node.core.types import EvidenceChunk, SourceKind
from corpus2node.graph.extract import (
    chunk_batches,
    extract_graph_candidates,
    merge_results,
    normalize_concept,
    normalize_relation,
)
from corpus2node.graph.schemas import ExtractedConcept, ExtractedRelation, GraphExtractionResult


def _chunk(index: int, text: str) -> EvidenceChunk:
    return EvidenceChunk(
        chunk_id=f"s-c{index}", source_id="s", source_type=SourceKind.pdf, text=text, summary=""
    )


def test_chunk_batches_drops_nothing():
    chunks = [_chunk(i, f"概念{i}是一种数据结构，用于组织和检索数据，便于复习。") for i in range(25)]
    batches = chunk_batches(chunks, max_chars=600, max_chunks=3)
    flat = [chunk for batch in batches for chunk in batch]
    assert len(flat) == 25  # B: full coverage, no stride sampling
    assert all(len(batch) <= 3 for batch in batches)


def test_extract_runs_every_batch_and_merges():
    chunks = [_chunk(i, f"二叉搜索树是一种树结构，用于高效查找。第{i}段补充说明内容。") for i in range(10)]
    seen: list[str] = []

    async def fake(prompt: str) -> GraphExtractionResult:
        seen.append(prompt)
        return GraphExtractionResult(
            concepts=[ExtractedConcept(name="二叉搜索树", canonical_name="二叉搜索树", definition="一种树")],
            relations=[
                ExtractedRelation(
                    source_canonical_name="二叉搜索树",
                    target_canonical_name="树结构",
                    edge_type="RELATES_TO",
                    relation_type="is_a",
                    confidence=0.9,
                )
            ],
        )

    result = asyncio.run(
        extract_graph_candidates(
            chunks, astructured=fake, batch_max_chars=400, batch_max_chunks=2, max_concurrency=4
        )
    )
    expected_batches = len(chunk_batches(chunks, max_chars=400, max_chunks=2))
    assert len(seen) == expected_batches  # every batch was processed concurrently
    assert len(result.concepts) == 1  # merged by canonical_name
    assert result.concepts[0].canonical_name == "二叉搜索树"
    assert len(result.relations) == 1


def test_merge_keeps_richer_definition_and_max_confidence():
    r1 = GraphExtractionResult(
        concepts=[ExtractedConcept(name="线性表", canonical_name="线性表", definition="短")],
        relations=[
            ExtractedRelation(
                source_canonical_name="线性表",
                target_canonical_name="数据结构",
                edge_type="RELATES_TO",
                relation_type="is_a",
                confidence=0.6,
            )
        ],
    )
    r2 = GraphExtractionResult(
        concepts=[ExtractedConcept(name="线性表结构", canonical_name="线性表", definition="一种按顺序排列元素的数据结构")],
        relations=[
            ExtractedRelation(
                source_canonical_name="线性表",
                target_canonical_name="数据结构",
                edge_type="RELATES_TO",
                relation_type="is_a",
                confidence=0.85,
            )
        ],
    )
    merged = merge_results([r1, r2])
    assert len(merged.concepts) == 1
    assert merged.concepts[0].definition == "一种按顺序排列元素的数据结构"
    assert len(merged.relations) == 1
    assert merged.relations[0].confidence == 0.85


def test_normalize_drops_noise_and_enforces_relation_rules():
    assert normalize_concept(ExtractedConcept(name="page 3", canonical_name="page 3")) is None
    assert normalize_concept(ExtractedConcept(name="B+树索引", canonical_name="B+树索引")) is not None

    # invalid relation_type on RELATES_TO -> dropped
    assert (
        normalize_relation(
            ExtractedRelation(
                source_canonical_name="线性表",
                target_canonical_name="数据结构",
                edge_type="RELATES_TO",
                relation_type="nope",
            )
        )
        is None
    )
    # non-RELATES_TO must not carry a relation_type
    contains = normalize_relation(
        ExtractedRelation(
            source_canonical_name="数据结构",
            target_canonical_name="线性表",
            edge_type="CONTAINS",
            relation_type="is_a",
        )
    )
    assert contains is not None
    assert contains.relation_type is None
