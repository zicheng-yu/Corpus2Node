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
from corpus2node.core.types import GenerateTestRequest, TestDocument
from corpus2node.exam import generate as exam_generate
from corpus2node.index.embeddings import EmbeddingProvenanceError
from corpus2node.llm.factory import LLMConfigError
from corpus2node.storage import local

router = APIRouter(tags=["test"])


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


async def _record_test(principal: Principal, test: TestDocument, owner_key: str) -> None:
    async with session_factory()() as db:
        await register_resource(
            db,
            principal=principal,
            resource_type="test",
            resource_key=f"{test.session_id}:{principal.user_id}",
            owner_user_id=principal.user_id,
            artifact_path=str(local.test_path(test.session_id, owner_key)),
        )
        await record_usage(
            db,
            principal,
            idempotency_key=f"test:{test.session_id}:{test.generated_at.isoformat()}",
            metric="ai_task",
            purpose="test",
            detail={
                "input_chars": sum(
                    len(chunk.text)
                    for artifact in local.list_ingest_artifacts(test.session_id)
                    for chunk in artifact.chunks
                ),
                "output_chars": len(test.model_dump_json()),
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


@router.post("/generate_test")
@router.post("/generate_exam", include_in_schema=False)
async def generate_test(
    payload: GenerateTestRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> TestDocument:
    principal = await _preflight(request, db, payload.session_id)
    owner_key = _owner_key(principal)
    try:
        with prompt_store.owner_context(owner_key):
            test = await exam_generate.generate_test(payload, owner_key=owner_key)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Session or graph not found. Build the graph first.") from exc
    except LLMConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except EmbeddingProvenanceError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if principal is not None and owner_key is not None:
        await _record_test(principal, test, owner_key)
    return test


@router.post("/generate_test/stream")
@router.post("/generate_exam/stream", include_in_schema=False)
async def generate_test_stream(
    payload: GenerateTestRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """Start (or attach to) a detached generation job and stream question/done/error events."""
    principal = await _preflight(request, db, payload.session_id)
    try:
        local.load_graph_artifact(payload.session_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Session or graph not found. Build the graph first.") from exc

    owner_key = _owner_key(principal)

    async def runner(emit: jobs.Emit) -> None:
        counter = {"n": 0}

        def on_question(question) -> None:
            counter["n"] += 1
            emit({"type": "question", "data": {"index": counter["n"], "question": question.model_dump(mode="json")}})

        with prompt_store.owner_context(owner_key):
            test = await exam_generate.generate_test(payload, on_question=on_question, owner_key=owner_key)
        if principal is not None and owner_key is not None:
            await _record_test(principal, test, owner_key)
        result_payload = test.model_dump(mode="json")
        emit({"type": "done", "data": {"test": result_payload, "exam": result_payload}})

    try:
        suffix = principal.user_id if principal is not None else "legacy"
        job = jobs.start(f"test:{payload.session_id}:{suffix}", runner, fingerprint=_fingerprint(payload))
    except jobs.JobConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _job_stream(job)


@router.get("/test/{session_id}/stream")
@router.get("/exam/{session_id}/stream", include_in_schema=False)
async def test_stream(
    session_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    principal = optional_principal(request)
    await require_resource_access(request, db, "session", str(session_id))
    owner_key = _owner_key(principal)
    suffix = principal.user_id if principal is not None else "legacy"
    job = jobs.get(f"test:{session_id}:{suffix}")
    if principal is None:
        job = job or jobs.get(f"test:{session_id}") or jobs.get(f"exam:{session_id}")
    if job is not None:
        return _job_stream(job)

    async def gen():
        try:
            test = local.load_test(session_id, owner_key)
            payload = test.model_dump(mode="json")
            yield _event({"type": "done", "data": {"test": payload, "exam": payload}})
        except FileNotFoundError:
            yield _event({"type": "idle", "data": {}})

    return StreamingResponse(gen(), media_type="text/event-stream")


@router.get("/test/{session_id}")
@router.get("/exam/{session_id}", include_in_schema=False)
async def get_test(
    session_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> TestDocument:
    principal = optional_principal(request)
    await require_resource_access(request, db, "session", str(session_id))
    try:
        return local.load_test(session_id, _owner_key(principal))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="No generated test for this session.") from exc


@router.delete("/test/{session_id}")
@router.delete("/exam/{session_id}", include_in_schema=False)
async def delete_test(
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
    local.delete_test(session_id, _owner_key(principal))
    if principal is not None:
        resource = await resource_for_principal(
            db,
            principal,
            "test",
            f"{session_id}:{principal.user_id}",
            owner_only=True,
        )
        if resource is not None:
            resource.status = "archived"
            await db.commit()
    return {"ok": True}


def _fingerprint(request: GenerateTestRequest) -> str:
    payload = request.model_dump(mode="json")
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
