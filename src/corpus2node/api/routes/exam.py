from __future__ import annotations

import hashlib
import json
from uuid import UUID

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from corpus2node import jobs
from corpus2node.core.types import ExamDocument, GenerateExamRequest
from corpus2node.exam import generate as exam_generate
from corpus2node.llm.factory import LLMConfigError
from corpus2node.storage import local

router = APIRouter(tags=["exam"])


def _event(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _job_stream(job: jobs.Job) -> StreamingResponse:
    async def gen():
        async for event in job.subscribe():
            yield _event(event)

    return StreamingResponse(gen(), media_type="text/event-stream")


@router.post("/generate_exam")
async def generate_exam(request: GenerateExamRequest) -> ExamDocument:
    try:
        return await exam_generate.generate_exam(request)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Session or graph not found. Build the graph first.") from exc
    except LLMConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/generate_exam/stream")
async def generate_exam_stream(request: GenerateExamRequest) -> StreamingResponse:
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

        exam = await exam_generate.generate_exam(request, on_question=on_question)
        emit({"type": "done", "data": {"exam": exam.model_dump(mode="json")}})

    try:
        job = jobs.start(f"exam:{request.session_id}", runner, fingerprint=_fingerprint(request))
    except jobs.JobConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _job_stream(job)


@router.get("/exam/{session_id}/stream")
async def exam_stream(session_id: UUID) -> StreamingResponse:
    job = jobs.get(f"exam:{session_id}")
    if job is not None:
        return _job_stream(job)

    async def gen():
        try:
            exam = local.load_exam(session_id)
            yield _event({"type": "done", "data": {"exam": exam.model_dump(mode="json")}})
        except FileNotFoundError:
            yield _event({"type": "idle", "data": {}})

    return StreamingResponse(gen(), media_type="text/event-stream")


@router.get("/exam/{session_id}")
def get_exam(session_id: UUID) -> ExamDocument:
    try:
        return local.load_exam(session_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="No generated exam for this session.") from exc


@router.delete("/exam/{session_id}")
def delete_exam(session_id: UUID) -> dict[str, bool]:
    try:
        local.load_session(session_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Session not found.") from exc
    local.delete_exam(session_id)
    return {"ok": True}


def _fingerprint(request: GenerateExamRequest) -> str:
    payload = request.model_dump(mode="json")
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
