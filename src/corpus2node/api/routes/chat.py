from __future__ import annotations

from corpus2node.core.clock import utcnow
from uuid import UUID

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from corpus2node.assistant import agent as chat_agent
from corpus2node.core.types import ChatCitation, ChatDocument, ChatMessage, ChatRequest, ChatResponse
from corpus2node.index.embeddings import get_embeddings
from corpus2node.llm import factory
from corpus2node.llm.credentials import Purpose
from corpus2node.llm.factory import LLMConfigError
from corpus2node.storage import local

router = APIRouter(prefix="/chat", tags=["chat"])


def _load_chat(session_id: UUID) -> ChatDocument:
    local.load_session(session_id)  # raises FileNotFoundError if the session is unknown
    try:
        return local.load_chat(session_id)
    except FileNotFoundError:
        return ChatDocument(session_id=session_id)


def _augment(message: str, request: ChatRequest) -> str:
    """Fold selected context (concept / selection) into the query the agent sees.

    The raw message is still what gets persisted/displayed; the agent receives the
    context preamble so it knows exactly which concept the user means.
    """
    items = request.context_items
    if not items:
        return message
    lines = ["[用户选中的上下文]"]
    for item in items:
        head = item.label or item.context_type
        suffix = f"（concept_id={item.concept_id}）" if item.concept_id else ""
        lines.append(f"- {head}{suffix}")
        if item.content:
            lines.append(f"  {item.content[:600]}")
    lines.append("")
    lines.append(f"[用户问题]\n{message}")
    return "\n".join(lines)


@router.get("/{session_id}")
def get_history(session_id: UUID) -> ChatDocument:
    try:
        return _load_chat(session_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Session not found.") from exc


@router.delete("/{session_id}")
def clear_history(session_id: UUID) -> ChatDocument:
    try:
        local.load_session(session_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Session not found.") from exc
    local.delete_chat(session_id)
    return ChatDocument(session_id=session_id)


@router.post("/message")
async def message(request: ChatRequest) -> ChatResponse:
    try:
        embeddings = get_embeddings()
        ctx = chat_agent.load_context(request.session_id, embeddings)
        model = factory.build_chat_model(Purpose.chat)
        chat = _load_chat(request.session_id)
        turn = await chat_agent.run_chat(_augment(request.message, request), ctx, model=model, history=chat.messages)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Session or graph not found. Build the graph first.") from exc
    except LLMConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    chat.messages.append(
        ChatMessage(role="user", content=request.message, context_items=request.context_items)
    )
    assistant = ChatMessage(role="assistant", content=turn.answer, citations=turn.citations)
    chat.messages.append(assistant)
    chat.updated_at = utcnow()
    local.save_chat(chat)

    return ChatResponse(
        chat=chat,
        assistant_message=assistant,
        citations=turn.citations,
        trace=turn.trace if request.debug else [],
        subgraph=turn.subgraph,
    )


@router.post("/stream")
async def stream(request: ChatRequest) -> StreamingResponse:
    try:
        embeddings = get_embeddings()
        ctx = chat_agent.load_context(request.session_id, embeddings)
        model = factory.build_chat_model(Purpose.chat)
        history = _load_chat(request.session_id).messages
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Session or graph not found. Build the graph first.") from exc
    except LLMConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    async def event_source():
        # Forward events to the client while capturing the final answer + citations
        # so the streamed turn is persisted just like POST /chat/message.
        answer_parts: list[str] = []
        citations: list[ChatCitation] = []
        failed = False
        async for event in chat_agent.stream_chat_events(_augment(request.message, request), ctx, model=model, history=history):
            if event.type == "token":
                answer_parts.append(str(event.data.get("text", "")))
            elif event.type == "citation":
                try:
                    citations.append(ChatCitation(**event.data))
                except Exception:
                    pass
            elif event.type == "error":
                failed = True
            yield f"data: {event.model_dump_json()}\n\n"

        if failed:
            return
        chat = _load_chat(request.session_id)
        chat.messages.append(
            ChatMessage(role="user", content=request.message, context_items=request.context_items)
        )
        chat.messages.append(
            ChatMessage(role="assistant", content="".join(answer_parts), citations=citations)
        )
        chat.updated_at = utcnow()
        local.save_chat(chat)

    return StreamingResponse(event_source(), media_type="text/event-stream")
