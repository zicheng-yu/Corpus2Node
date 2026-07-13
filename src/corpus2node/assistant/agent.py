"""Online tool-calling agent with evidence retrieval and citation validation."""
from __future__ import annotations

import logging
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass
from uuid import UUID

from langchain.agents import create_agent
from langchain_core.embeddings import Embeddings
from langchain_core.messages import AIMessage, HumanMessage

from corpus2node import prompt_store
from corpus2node.assistant.tools import ChatContext, build_tools
from corpus2node.core.types import ChatCitation, ChatMessage, ChatStreamEvent, ChatTraceStep, SubgraphResponse
from corpus2node.index import search
from corpus2node.index.embeddings import ensure_embedding_compatible
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
    ensure_embedding_compatible(graph, embeddings)
    chunks = [chunk for artifact in local.list_ingest_artifacts(session_id) for chunk in artifact.chunks]
    return ChatContext(graph, chunks, embeddings)


async def run_chat(query: str, ctx: ChatContext, *, model, history: list[ChatMessage] | None = None) -> ChatTurn:
    logger.info("chat: query=%r", query[:80])
    query = _with_prefetch_context(ctx, query)
    agent = create_agent(model=model, tools=build_tools(ctx), system_prompt=SYSTEM_PROMPT + prompt_store.custom_block("chat"))
    result = await agent.ainvoke({"messages": _agent_messages(query, history)})
    messages = result.get("messages", [])
    answer = _message_text(messages[-1]) if messages else ""
    trace = _trace_from_messages(messages)
    _ensure_grounding(ctx, query)
    answer = _validate_grounded_answer(answer, ctx)
    cited_indices = _citation_indices(answer, len(ctx.retrievals))
    turn = ChatTurn(
        answer=answer,
        citations=ctx.citations(cited_indices),
        trace=trace,
        subgraph=_choose_subgraph(ctx, query),
    )
    logger.info(
        "chat: %d citations, %d trace steps, subgraph_nodes=%d",
        len(turn.citations), len(turn.trace), len(turn.subgraph.nodes) if turn.subgraph else 0,
    )
    return turn


async def stream_chat_events(
    query: str, ctx: ChatContext, *, model, history: list[ChatMessage] | None = None
) -> AsyncIterator[ChatStreamEvent]:
    yield ChatStreamEvent(type="start", data={"query": query})
    query = _with_prefetch_context(ctx, query)
    agent = create_agent(model=model, tools=build_tools(ctx), system_prompt=SYSTEM_PROMPT + prompt_store.custom_block("chat"))
    answer_parts: list[str] = []
    try:
        async for event in agent.astream_events({"messages": _agent_messages(query, history)}, version="v2"):
            kind = event.get("event")
            if kind == "on_chat_model_stream":
                text = _message_text(event["data"]["chunk"])
                if text:
                    answer_parts.append(text)
            elif kind == "on_chat_model_end" and not answer_parts:
                # Some providers only expose the final text at model-end.
                text = _message_text(event["data"].get("output"))
                if text:
                    answer_parts.append(text)
            elif kind == "on_tool_start":
                yield ChatStreamEvent(type="tool_call", data={"tool": event.get("name", ""), "args": event["data"].get("input", {})})
            elif kind == "on_tool_end":
                yield ChatStreamEvent(type="retrieval", data={"tool": event.get("name", ""), "total": len(ctx.retrievals)})
                if event.get("name") == "get_subgraph" and ctx.subgraph is not None:
                    yield ChatStreamEvent(type="subgraph", data=ctx.subgraph.model_dump(mode="json"))

        _ensure_grounding(ctx, query)
        raw_answer = "".join(answer_parts)
        answer = _validate_grounded_answer(raw_answer, ctx)
        answer_parts = [answer]
        # Buffer model tokens until deterministic citation/support validation finishes;
        # this prevents an unsupported draft from flashing in the UI or being persisted.
        yield ChatStreamEvent(type="token", data={"text": answer})
        subgraph = _choose_subgraph(ctx, query)
        if subgraph is not None:
            yield ChatStreamEvent(type="subgraph", data=subgraph.model_dump(mode="json"))
        cited_indices = _citation_indices("".join(answer_parts), len(ctx.retrievals))
        for citation in ctx.citations(cited_indices):
            yield ChatStreamEvent(type="citation", data=citation.model_dump(mode="json"))
        yield ChatStreamEvent(type="done", data={"answer": "".join(answer_parts)})
    except Exception as exc:  # surface as a terminal error event, never crash the stream
        logger.exception("chat stream failed")
        yield ChatStreamEvent(type="error", data={"message": str(exc)})


def _ensure_grounding(ctx: ChatContext, query: str) -> None:
    if not ctx.retrievals:
        ctx.add(search.local_search(query, graph=ctx.graph, chunks=ctx.chunks, embeddings=ctx.embeddings, limit=ctx.chunk_limit))


def _with_prefetch_context(ctx: ChatContext, query: str) -> str:
    """Run a deterministic first retrieval so the model sees citeable evidence even if it skips tools."""
    _ensure_grounding(ctx, query)
    if not ctx.retrievals:
        return query
    lines = ["[系统预检索到的可引用资料]"]
    for result in ctx.retrievals[: ctx.chunk_limit]:
        marker = ctx.index_of(result)
        locator = f"（{result.locator}）" if result.locator else ""
        lines.append(f"[{marker}] {result.title}{locator}: {result.snippet}")
    lines.extend(["", "[用户问题]", query])
    return "\n".join(lines)


def _agent_messages(query: str, history: list[ChatMessage] | None = None) -> list:
    messages: list = []
    for item in (history or [])[-12:]:
        content = item.content.strip()
        if not content:
            continue
        if item.role == "user":
            messages.append(HumanMessage(content=content))
        elif item.role == "assistant":
            messages.append(AIMessage(content=content))
    messages.append(HumanMessage(content=query))
    return messages


def _validate_grounded_answer(answer: str, ctx: ChatContext) -> str:
    """Remove invalid markers and reject answers with no lexical evidence support.

    This is deliberately conservative: it does not claim semantic entailment. It
    guarantees that every returned marker maps to a real retrieval and that a
    topically unrelated answer is not presented as grounded.
    """
    answer = _remove_invalid_markers(answer, len(ctx.retrievals)).strip()
    if not ctx.retrievals:
        return "现有资料不足以可靠回答该问题。"
    if answer and not _answer_overlaps_evidence(answer, ctx):
        refs = " ".join(f"[{citation.index}]" for citation in ctx.citations()[:2])
        return f"现有资料不足以支持模型生成的回答，请补充资料或缩小问题范围。\n\n参考来源：{refs}"
    suffix = _missing_citation_suffix(answer, ctx)
    return answer + suffix if suffix else answer


def _missing_citation_suffix(answer: str, ctx: ChatContext) -> str:
    if not ctx.retrievals or _citation_indices(answer, len(ctx.retrievals)):
        return ""
    refs = " ".join(f"[{citation.index}]" for citation in ctx.citations()[:2])
    return f"\n\n参考来源：{refs}"


def _remove_invalid_markers(text: str, retrieval_count: int) -> str:
    def replace(match: re.Match[str]) -> str:
        index = int(match.group(1))
        return match.group(0) if 1 <= index <= retrieval_count else ""

    return re.sub(r"\[(\d+)\]", replace, text or "")


def _citation_indices(text: str, retrieval_count: int) -> set[int]:
    return {
        index
        for value in re.findall(r"\[(\d+)\]", text or "")
        if 1 <= (index := int(value)) <= retrieval_count
    }


def _answer_overlaps_evidence(answer: str, ctx: ChatContext) -> bool:
    answer_tokens = _semantic_tokens(re.sub(r"\[\d+\]", "", answer))
    if not answer_tokens:
        return False
    evidence = " ".join(
        f"{result.title} {result.snippet} {result.metadata.get('evidence_snippet', '')}"
        for result in ctx.retrievals
    )
    evidence_tokens = _semantic_tokens(evidence)
    overlap = answer_tokens & evidence_tokens
    return len(overlap) >= 2 or len(overlap) / max(1, len(answer_tokens)) >= 0.12


def _semantic_tokens(text: str) -> set[str]:
    lowered = text.lower()
    words = set(re.findall(r"[a-z][a-z0-9_+-]{2,}", lowered))
    chinese = re.sub(r"[^一-鿿]", "", lowered)
    bigrams = {chinese[index : index + 2] for index in range(max(0, len(chinese) - 1))}
    return words | bigrams


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
