from __future__ import annotations

from corpus2node.core.clock import utcnow
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from corpus2node.accounts.database import get_db, session_factory
from corpus2node.accounts.dependencies import optional_principal, require_resource_access
from corpus2node.accounts.schemas import Principal
from corpus2node.accounts.service import (
    AuthorizationError,
    QuotaError,
    enforce_quota,
    ensure_writable,
    record_usage,
    register_resource,
    resource_for_principal,
    require_role,
)
from corpus2node.assistant import agent as chat_agent
from corpus2node.core.types import ChatCitation, ChatDocument, ChatMessage, ChatRequest, ChatResponse
from corpus2node.core.concurrency import keyed_lock
from corpus2node.index.embeddings import EmbeddingProvenanceError, get_embeddings
from corpus2node.llm import factory
from corpus2node.llm.credentials import Purpose
from corpus2node.llm.factory import LLMConfigError
from corpus2node import prompt_store
from corpus2node.storage import local

router = APIRouter(prefix="/chat", tags=["chat"])


def _owner_key(principal: Principal | None) -> str | None:
    if principal is None or principal.organization_id is None:
        return None
    return f"{principal.organization_id}/{principal.user_id}"


def _load_chat(session_id: UUID, owner_key: str | None = None) -> ChatDocument:
    local.load_session(session_id)  # raises FileNotFoundError if the session is unknown
    try:
        return local.load_chat(session_id, owner_key)
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
async def get_history(
    session_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> ChatDocument:
    principal = optional_principal(request)
    await require_resource_access(request, db, "session", str(session_id))
    try:
        return _load_chat(session_id, _owner_key(principal))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Session not found.") from exc


@router.delete("/{session_id}")
async def clear_history(
    session_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> ChatDocument:
    principal = optional_principal(request)
    await require_resource_access(request, db, "session", str(session_id))
    if principal is not None:
        try:
            await ensure_writable(db, principal)
        except AuthorizationError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
    try:
        local.load_session(session_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Session not found.") from exc
    local.delete_chat(session_id, _owner_key(principal))
    if principal is not None:
        resource = await resource_for_principal(
            db,
            principal,
            "chat",
            f"{session_id}:{principal.user_id}",
            owner_only=True,
        )
        if resource is not None:
            resource.status = "archived"
            await db.commit()
    return ChatDocument(session_id=session_id)


@router.post("/message")
async def message(
    payload: ChatRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> ChatResponse:
    principal = optional_principal(request)
    await require_resource_access(request, db, "session", str(payload.session_id))
    if principal is not None:
        try:
            require_role(principal, "member")
            await enforce_quota(db, principal, "chat_turn")
        except AuthorizationError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except QuotaError as exc:
            raise HTTPException(status_code=429, detail=exc.detail()) from exc
    owner_key = _owner_key(principal)
    try:
        embeddings = get_embeddings()
        ctx = chat_agent.load_context(payload.session_id, embeddings)
        model = factory.build_chat_model(Purpose.chat)
        async with keyed_lock(f"chat:{payload.session_id}:{owner_key or 'legacy'}"):
            chat = _load_chat(payload.session_id, owner_key)
            with prompt_store.owner_context(owner_key):
                turn = await chat_agent.run_chat(
                    _augment(payload.message, payload), ctx, model=model, history=chat.messages
                )
            chat.messages.append(
                ChatMessage(role="user", content=payload.message, context_items=payload.context_items)
            )
            assistant = ChatMessage(role="assistant", content=turn.answer, citations=turn.citations)
            chat.messages.append(assistant)
            chat.updated_at = utcnow()
            local.save_chat(chat, owner_key)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Session or graph not found. Build the graph first.") from exc
    except LLMConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except EmbeddingProvenanceError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    if principal is not None:
        await register_resource(
            db,
            principal=principal,
            resource_type="chat",
            resource_key=f"{payload.session_id}:{principal.user_id}",
            owner_user_id=principal.user_id,
            artifact_path=str(local.chat_path(payload.session_id, owner_key)),
        )
        await record_usage(
            db,
            principal,
            idempotency_key=f"chat:{payload.session_id}:{chat.updated_at.isoformat()}",
            metric="chat_turn",
            purpose="chat",
            detail={"input_chars": len(payload.message), "output_chars": len(turn.answer)},
        )
        await db.commit()
    return ChatResponse(
        chat=chat,
        assistant_message=assistant,
        citations=turn.citations,
        trace=turn.trace if payload.debug else [],
        subgraph=turn.subgraph,
    )


@router.post("/stream")
async def stream(
    payload: ChatRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    principal = optional_principal(request)
    await require_resource_access(request, db, "session", str(payload.session_id))
    if principal is not None:
        try:
            require_role(principal, "member")
            await enforce_quota(db, principal, "chat_turn")
        except AuthorizationError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except QuotaError as exc:
            raise HTTPException(status_code=429, detail=exc.detail()) from exc
    owner_key = _owner_key(principal)
    try:
        embeddings = get_embeddings()
        ctx = chat_agent.load_context(payload.session_id, embeddings)
        model = factory.build_chat_model(Purpose.chat)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Session or graph not found. Build the graph first.") from exc
    except LLMConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except EmbeddingProvenanceError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    async def event_source():
        # Forward events to the client while capturing the final answer + citations
        # so the streamed turn is persisted just like POST /chat/message.
        async with keyed_lock(f"chat:{payload.session_id}:{owner_key or 'legacy'}"):
            history = _load_chat(payload.session_id, owner_key).messages
            answer_parts: list[str] = []
            citations: list[ChatCitation] = []
            failed = False
            with prompt_store.owner_context(owner_key):
                async for event in chat_agent.stream_chat_events(
                    _augment(payload.message, payload), ctx, model=model, history=history
                ):
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
            chat = _load_chat(payload.session_id, owner_key)
            chat.messages.append(
                ChatMessage(role="user", content=payload.message, context_items=payload.context_items)
            )
            chat.messages.append(
                ChatMessage(role="assistant", content="".join(answer_parts), citations=citations)
            )
            chat.updated_at = utcnow()
            local.save_chat(chat, owner_key)
            if principal is not None:
                async with session_factory()() as usage_db:
                    await register_resource(
                        usage_db,
                        principal=principal,
                        resource_type="chat",
                        resource_key=f"{payload.session_id}:{principal.user_id}",
                        owner_user_id=principal.user_id,
                        artifact_path=str(local.chat_path(payload.session_id, owner_key)),
                    )
                    await record_usage(
                        usage_db,
                        principal,
                        idempotency_key=f"chat-stream:{payload.session_id}:{chat.updated_at.isoformat()}",
                        metric="chat_turn",
                        purpose="chat",
                        detail={
                            "input_chars": len(payload.message),
                            "output_chars": len("".join(answer_parts)),
                        },
                    )
                    await usage_db.commit()

    return StreamingResponse(event_source(), media_type="text/event-stream")
