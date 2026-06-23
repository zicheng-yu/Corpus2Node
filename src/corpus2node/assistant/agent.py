"""The online chat agent: a single tool-calling agent that must ground answers in
retrieved chunks/concepts, with a structured trace + subgraph + citations.

Grounding is *guaranteed*: if the model answers without calling a tool, we run a
fallback local_search so every answer carries at least one citation + a subgraph.
"""
from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from uuid import UUID

from langchain.agents import create_agent
from langchain_core.embeddings import Embeddings
from langchain_core.messages import HumanMessage

from corpus2node.assistant.tools import ChatContext, build_tools
from corpus2node.core.types import ChatCitation, ChatStreamEvent, ChatTraceStep, SubgraphResponse
from corpus2node.index import search
from corpus2node.storage import local

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """你是 Corpus2Node 的资料学习助手。
- 必须先调用检索工具（retrieve_chunks / search_concepts / get_subgraph），再回答；只能基于检索到的图谱概念与原文片段作答，不要编造图谱外内容。
- 回答中用 [n] 标注引用，n 对应工具返回结果的编号；至少引用一个来源。
- 若检索不到足够信息，明确说明缺什么，并给出下一步可问的问题。
- 面向复习，简洁清晰，可用 Markdown。
"""


@dataclass
class ChatTurn:
    answer: str
    citations: list[ChatCitation]
    trace: list[ChatTraceStep]
    subgraph: SubgraphResponse | None


def load_context(session_id: UUID, embeddings: Embeddings) -> ChatContext:
    graph = local.load_graph_artifact(session_id)
    chunks = [chunk for artifact in local.list_ingest_artifacts(session_id) for chunk in artifact.chunks]
    return ChatContext(graph, chunks, embeddings)


async def run_chat(query: str, ctx: ChatContext, *, model) -> ChatTurn:
    logger.info("chat: query=%r", query[:80])
    agent = create_agent(model=model, tools=build_tools(ctx), system_prompt=SYSTEM_PROMPT)
    result = await agent.ainvoke({"messages": [HumanMessage(content=query)]})
    messages = result.get("messages", [])
    answer = _message_text(messages[-1]) if messages else ""
    trace = _trace_from_messages(messages)
    _ensure_grounding(ctx, query)
    turn = ChatTurn(
        answer=answer,
        citations=ctx.citations(),
        trace=trace,
        subgraph=_choose_subgraph(ctx, query),
    )
    logger.info(
        "chat: %d citations, %d trace steps, subgraph_nodes=%d",
        len(turn.citations), len(turn.trace), len(turn.subgraph.nodes) if turn.subgraph else 0,
    )
    return turn


async def stream_chat_events(query: str, ctx: ChatContext, *, model) -> AsyncIterator[ChatStreamEvent]:
    yield ChatStreamEvent(type="start", data={"query": query})
    agent = create_agent(model=model, tools=build_tools(ctx), system_prompt=SYSTEM_PROMPT)
    answer_parts: list[str] = []
    try:
        async for event in agent.astream_events({"messages": [HumanMessage(content=query)]}, version="v2"):
            kind = event.get("event")
            if kind == "on_chat_model_stream":
                text = _message_text(event["data"]["chunk"])
                if text:
                    answer_parts.append(text)
                    yield ChatStreamEvent(type="token", data={"text": text})
            elif kind == "on_chat_model_end" and not answer_parts:
                # model didn't stream token-by-token — emit the final text as one token
                text = _message_text(event["data"].get("output"))
                if text:
                    answer_parts.append(text)
                    yield ChatStreamEvent(type="token", data={"text": text})
            elif kind == "on_tool_start":
                yield ChatStreamEvent(type="tool_call", data={"tool": event.get("name", ""), "args": event["data"].get("input", {})})
            elif kind == "on_tool_end":
                yield ChatStreamEvent(type="retrieval", data={"tool": event.get("name", ""), "total": len(ctx.retrievals)})
                if event.get("name") == "get_subgraph" and ctx.subgraph is not None:
                    yield ChatStreamEvent(type="subgraph", data=ctx.subgraph.model_dump(mode="json"))

        _ensure_grounding(ctx, query)
        subgraph = _choose_subgraph(ctx, query)
        if subgraph is not None:
            yield ChatStreamEvent(type="subgraph", data=subgraph.model_dump(mode="json"))
        for citation in ctx.citations():
            yield ChatStreamEvent(type="citation", data=citation.model_dump(mode="json"))
        yield ChatStreamEvent(type="done", data={"answer": "".join(answer_parts)})
    except Exception as exc:  # surface as a terminal error event, never crash the stream
        logger.exception("chat stream failed")
        yield ChatStreamEvent(type="error", data={"message": str(exc)})


def _ensure_grounding(ctx: ChatContext, query: str) -> None:
    if not ctx.retrievals:
        ctx.add(search.local_search(query, graph=ctx.graph, chunks=ctx.chunks, embeddings=ctx.embeddings, limit=ctx.chunk_limit))


def _choose_subgraph(ctx: ChatContext, query: str) -> SubgraphResponse | None:
    # a get_subgraph tool call can return an EMPTY subgraph (bad/unknown id); an empty
    # SubgraphResponse is still truthy, so only keep it if it has nodes, else fall back.
    if ctx.subgraph and ctx.subgraph.nodes:
        return ctx.subgraph
    return _fallback_subgraph(ctx, query)


def _fallback_subgraph(ctx: ChatContext, query: str) -> SubgraphResponse | None:
    concept_ids = [result.ref_id for result in ctx.retrievals if result.kind == "concept"]
    if not concept_ids:
        # center on the concept most relevant to the question
        hits = search.search_concepts(query, graph=ctx.graph, embeddings=ctx.embeddings, limit=1)
        concept_ids = [hit.ref_id for hit in hits]
    if not concept_ids and ctx.graph.concepts:
        concept_ids = [max(ctx.graph.concepts, key=lambda c: c.importance_score).concept_id]
    if not concept_ids:
        return None
    return search.get_subgraph(
        ctx.graph, concept_ids[0], depth=ctx.subgraph_depth, max_nodes=ctx.subgraph_max_nodes
    )


def _trace_from_messages(messages: list) -> list[ChatTraceStep]:
    steps: list[ChatTraceStep] = []
    counter = 0
    for message in messages:
        for call in getattr(message, "tool_calls", None) or []:
            counter += 1
            steps.append(
                ChatTraceStep(
                    step=counter,
                    type="tool_call",
                    tool=call.get("name", ""),
                    args=call.get("args", {}) or {},
                    summary=f"调用 {call.get('name', '')}",
                )
            )
    counter += 1
    steps.append(ChatTraceStep(step=counter, type="answer", summary="基于检索结果生成回答"))
    return steps


def _message_text(message) -> str:
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                parts.append(item.get("text", ""))
        return "".join(parts)
    return str(content)
