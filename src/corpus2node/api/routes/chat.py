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
        turn = await chat_agent.run_chat(request.message, ctx, model=model)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Session or graph not found. Build the graph first.") from exc
    except LLMConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    chat = _load_chat(request.session_id)
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
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Session or graph not found. Build the graph first.") from exc
    except LLMConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    async def event_source():
        # Forward events to the client while capturing the final answer + citations
        # so the streamed turn is persisted just like POST /chat/message.
        answer_parts: list[str] = []
        citations: list[ChatCitation] = []
        async for event in chat_agent.stream_chat_events(request.message, ctx, model=model):
            if event.type == "token":
                answer_parts.append(str(event.data.get("text", "")))
            elif event.type == "citation":
                try:
                    citations.append(ChatCitation(**event.data))
                except Exception:
                    pass
            yield f"data: {event.model_dump_json()}\n\n"

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
