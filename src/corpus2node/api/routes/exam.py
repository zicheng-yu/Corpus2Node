from __future__ import annotations

import hashlib
import json
from uuid import UUID

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from corpus2node import jobs
from corpus2node.core.types import GenerateTestRequest, TestDocument
from corpus2node.exam import generate as exam_generate
from corpus2node.index.embeddings import EmbeddingProvenanceError
from corpus2node.llm.factory import LLMConfigError
from corpus2node.storage import local

router = APIRouter(tags=["test"])


def _event(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _job_stream(job: jobs.Job) -> StreamingResponse:
    async def gen():
        async for event in job.subscribe():
            yield _event(event)

    return StreamingResponse(gen(), media_type="text/event-stream")


@router.post("/generate_test")
@router.post("/generate_exam", include_in_schema=False)
async def generate_test(request: GenerateTestRequest) -> TestDocument:
    try:
        return await exam_generate.generate_test(request)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Session or graph not found. Build the graph first.") from exc
    except LLMConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except EmbeddingProvenanceError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/generate_test/stream")
@router.post("/generate_exam/stream", include_in_schema=False)
async def generate_test_stream(request: GenerateTestRequest) -> StreamingResponse:
    """Start (or attach to) a detached generation job and stream question/done/error events."""
    try:
        local.load_graph_artifact(request.session_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Session or graph not found. Build the graph first.") from exc

    async def runner(emit: jobs.Emit) -> None:
        counter = {"n": 0}

        def on_question(question) -> None:
            counter["n"] += 1
            emit({"type": "question", "data": {"index": counter["n"], "question": question.model_dump(mode="json")}})

        test = await exam_generate.generate_test(request, on_question=on_question)
        payload = test.model_dump(mode="json")
        emit({"type": "done", "data": {"test": payload, "exam": payload}})

    try:
        job = jobs.start(f"test:{request.session_id}", runner, fingerprint=_fingerprint(request))
    except jobs.JobConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _job_stream(job)


@router.get("/test/{session_id}/stream")
@router.get("/exam/{session_id}/stream", include_in_schema=False)
async def test_stream(session_id: UUID) -> StreamingResponse:
    job = jobs.get(f"test:{session_id}") or jobs.get(f"exam:{session_id}")
    if job is not None:
        return _job_stream(job)

    async def gen():
        try:
            test = local.load_test(session_id)
            payload = test.model_dump(mode="json")
            yield _event({"type": "done", "data": {"test": payload, "exam": payload}})
        except FileNotFoundError:
            yield _event({"type": "idle", "data": {}})

    return StreamingResponse(gen(), media_type="text/event-stream")


@router.get("/test/{session_id}")
@router.get("/exam/{session_id}", include_in_schema=False)
def get_test(session_id: UUID) -> TestDocument:
    try:
        return local.load_test(session_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="No generated test for this session.") from exc


@router.delete("/test/{session_id}")
@router.delete("/exam/{session_id}", include_in_schema=False)
def delete_test(session_id: UUID) -> dict[str, bool]:
    try:
        local.load_session(session_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Session not found.") from exc
    local.delete_test(session_id)
    return {"ok": True}


def _fingerprint(request: GenerateTestRequest) -> str:
    payload = request.model_dump(mode="json")
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
