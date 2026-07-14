from __future__ import annotations

import hashlib
import json
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from corpus2node import jobs
from corpus2node import prompt_store
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
from corpus2node.core.types import GenerateNotesRequest, NoteDocument
from corpus2node.index.embeddings import EmbeddingProvenanceError
from corpus2node.llm.factory import LLMConfigError
from corpus2node.notes import generate as notes_generate
from corpus2node.storage import local

router = APIRouter(tags=["notes"])


def _owner_key(principal: Principal | None) -> str | None:
    if principal is None or principal.organization_id is None:
        return None
    return f"{principal.organization_id}/{principal.user_id}"


async def _preflight(request: Request, db: AsyncSession, session_id: UUID) -> Principal | None:
    principal = optional_principal(request)
    await require_resource_access(request, db, "session", str(session_id))
    if principal is not None:
        try:
            require_role(principal, "member")
            await enforce_quota(db, principal, "ai_task")
        except AuthorizationError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except QuotaError as exc:
            raise HTTPException(status_code=429, detail=exc.detail()) from exc
    return principal


async def _record_note(principal: Principal, note: NoteDocument, owner_key: str) -> None:
    async with session_factory()() as db:
        await register_resource(
            db,
            principal=principal,
            resource_type="note",
            resource_key=f"{note.session_id}:{principal.user_id}",
            owner_user_id=principal.user_id,
            artifact_path=str(local.notes_path(note.session_id, owner_key)),
        )
        await record_usage(
            db,
            principal,
            idempotency_key=f"notes:{note.session_id}:{note.generated_at.isoformat()}",
            metric="ai_task",
            purpose="notes",
            detail={
                "input_chars": sum(
                    len(chunk.text)
                    for artifact in local.list_ingest_artifacts(note.session_id)
                    for chunk in artifact.chunks
                ),
                "output_chars": len(note.model_dump_json()),
            },
        )
        await db.commit()


def _event(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _job_stream(job: jobs.Job) -> StreamingResponse:
    async def gen():
        async for event in job.subscribe():
            yield _event(event)

    return StreamingResponse(gen(), media_type="text/event-stream")


@router.post("/generate_notes")
async def generate_notes(
    payload: GenerateNotesRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> NoteDocument:
    principal = await _preflight(request, db, payload.session_id)
    owner_key = _owner_key(principal)
    try:
        with prompt_store.owner_context(owner_key):
            note = await notes_generate.generate_notes(payload, owner_key=owner_key)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Session or graph not found. Build the graph first.") from exc
    except LLMConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except EmbeddingProvenanceError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if principal is not None and owner_key is not None:
        await _record_note(principal, note, owner_key)
    return note


@router.post("/generate_notes/stream")
async def generate_notes_stream(
    payload: GenerateNotesRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """Start (or attach to) a detached generation job and stream section/done/error events."""
    principal = await _preflight(request, db, payload.session_id)
    try:
        local.load_graph_artifact(payload.session_id)  # 404 fast if the graph isn't built
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Session or graph not found. Build the graph first.") from exc

    owner_key = _owner_key(principal)

    async def runner(emit: jobs.Emit) -> None:
        counter = {"n": 0}

        def on_section(title: str, content_md: str) -> None:
            counter["n"] += 1
            emit({"type": "section", "data": {"index": counter["n"], "title": title, "content_md": content_md}})

        with prompt_store.owner_context(owner_key):
            note = await notes_generate.generate_notes(payload, on_section=on_section, owner_key=owner_key)
        if principal is not None and owner_key is not None:
            await _record_note(principal, note, owner_key)
        emit({"type": "done", "data": {"note": note.model_dump(mode="json")}})

    try:
        suffix = principal.user_id if principal is not None else "legacy"
        job = jobs.start(f"notes:{payload.session_id}:{suffix}", runner, fingerprint=_fingerprint(payload))
    except jobs.JobConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _job_stream(job)


@router.get("/notes/{session_id}/stream")
async def notes_stream(
    session_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """Attach to an in-flight job (replay + live); else replay the saved note, else idle."""
    principal = optional_principal(request)
    await require_resource_access(request, db, "session", str(session_id))
    owner_key = _owner_key(principal)
    suffix = principal.user_id if principal is not None else "legacy"
    job = jobs.get(f"notes:{session_id}:{suffix}") or (jobs.get(f"notes:{session_id}") if principal is None else None)
    if job is not None:
        return _job_stream(job)

    async def gen():
        try:
            note = local.load_note(session_id, owner_key)
            yield _event({"type": "done", "data": {"note": note.model_dump(mode="json")}})
        except FileNotFoundError:
            yield _event({"type": "idle", "data": {}})

    return StreamingResponse(gen(), media_type="text/event-stream")


@router.get("/notes/{session_id}")
async def get_notes(
    session_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> NoteDocument:
    principal = optional_principal(request)
    await require_resource_access(request, db, "session", str(session_id))
    try:
        return local.load_note(session_id, _owner_key(principal))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="No generated notes for this session.") from exc


@router.delete("/notes/{session_id}")
async def delete_notes(
    session_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, bool]:
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
    local.delete_note(session_id, _owner_key(principal))
    if principal is not None:
        resource = await resource_for_principal(
            db,
            principal,
            "note",
            f"{session_id}:{principal.user_id}",
            owner_only=True,
        )
        if resource is not None:
            resource.status = "archived"
            await db.commit()
    return {"ok": True}


def _fingerprint(request: GenerateNotesRequest) -> str:
    payload = request.model_dump(mode="json")
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
