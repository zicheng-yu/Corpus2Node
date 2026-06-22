from __future__ import annotations

import asyncio
import uuid

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import PrivateAttr

from corpus2node.assistant.agent import run_chat, stream_chat_events
from corpus2node.assistant.tools import ChatContext
from corpus2node.graph.build import build_graph_artifact
from corpus2node.graph.schemas import ExtractedConcept, ExtractedRelation, GraphExtractionResult
from corpus2node.core.types import EvidenceChunk, SourceKind
from corpus2node.index.embeddings import HashingEmbeddings

EMB = HashingEmbeddings(dims=256)


class FakeChatModel(BaseChatModel):
    """Scripted chat model: returns the next AIMessage per call; tool calls honored."""

    responses: list[BaseMessage] = []
    _cursor: int = PrivateAttr(default=0)

    def bind_tools(self, tools, **kwargs):  # noqa: ANN001 - tools ignored; we script tool_calls
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        index = min(self._cursor, len(self.responses) - 1)
        self._cursor += 1
        return ChatResult(generations=[ChatGeneration(message=self.responses[index])])

    @property
    def _llm_type(self) -> str:
        return "fake-chat"


def _context() -> ChatContext:
    chunks = [
        EvidenceChunk(
            chunk_id=f"s-c{i}", source_id="s", source_type=SourceKind.pdf,
            text=text, summary="", embedding=EMB.embed_query(text),
        )
        for i, text in enumerate(["二叉搜索树 是 一种 树 ，用于 高效 查找", "平衡树 是 二叉搜索树 的 改进"])
    ]
    candidates = GraphExtractionResult(
        concepts=[
            ExtractedConcept(name="二叉搜索树", canonical_name="二叉搜索树", definition="用于 查找 的 树"),
            ExtractedConcept(name="平衡树", canonical_name="平衡树", definition="二叉搜索树 的 改进"),
            ExtractedConcept(name="树结构", canonical_name="树结构", definition="层次 数据 结构"),
        ],
        relations=[
            ExtractedRelation(
                source_canonical_name="二叉搜索树", target_canonical_name="树结构",
                edge_type="RELATES_TO", relation_type="is_a", confidence=0.9,
            )
        ],
    )
    graph = build_graph_artifact(uuid.uuid4(), chunks, candidates, embeddings=EMB)
    return ChatContext(graph, chunks, EMB)


def test_run_chat_forces_grounding_when_model_skips_tools():
    fake = FakeChatModel(responses=[AIMessage(content="二叉搜索树用于查找。[1]")])
    turn = asyncio.run(run_chat("二叉搜索树是什么", _context(), model=fake))
    assert turn.answer
    assert len(turn.citations) >= 1  # fallback local_search guarantees a citation
    assert turn.subgraph is not None and turn.subgraph.nodes
    assert turn.trace and turn.trace[-1].type == "answer"


def test_run_chat_uses_tool_results_as_citations():
    fake = FakeChatModel(
        responses=[
            AIMessage(content="", tool_calls=[{"name": "search_concepts", "args": {"query": "二叉搜索树"}, "id": "c1"}]),
            AIMessage(content="二叉搜索树是一种树。[1]"),
        ]
    )
    turn = asyncio.run(run_chat("二叉搜索树", _context(), model=fake))
    assert len(turn.citations) >= 1
    assert any(citation.kind == "concept" for citation in turn.citations)
    assert any(step.type == "tool_call" and step.tool == "search_concepts" for step in turn.trace)


def test_stream_emits_valid_event_schema():
    fake = FakeChatModel(responses=[AIMessage(content="答案 [1]")])

    async def collect():
        return [event async for event in stream_chat_events("问题", _context(), model=fake)]

    events = asyncio.run(collect())
    types = [event.type for event in events]
    allowed = {"start", "token", "tool_call", "retrieval", "subgraph", "citation", "done", "error"}
    assert set(types) <= allowed
    assert types[0] == "start" and types[-1] == "done"
    assert "token" in types
    assert "citation" in types  # grounding fallback produced at least one
