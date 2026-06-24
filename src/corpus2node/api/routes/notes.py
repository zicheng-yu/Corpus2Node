from __future__ import annotations

import json
from uuid import UUID

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from corpus2node import jobs
from corpus2node.core.types import GenerateNotesRequest, NoteDocument
from corpus2node.llm.factory import LLMConfigError
from corpus2node.notes import generate as notes_generate
from corpus2node.storage import local

router = APIRouter(tags=["notes"])


def _event(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _job_stream(job: jobs.Job) -> StreamingResponse:
    async def gen():
        async for event in job.subscribe():
            yield _event(event)

    return StreamingResponse(gen(), media_type="text/event-stream")


@router.post("/generate_notes")
async def generate_notes(request: GenerateNotesRequest) -> NoteDocument:
    try:
        return await notes_generate.generate_notes(request)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Session or graph not found. Build the graph first.") from exc
    except LLMConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/generate_notes/stream")
async def generate_notes_stream(request: GenerateNotesRequest) -> StreamingResponse:
    """Start (or attach to) a detached generation job and stream section/done/error events."""
    try:
        local.load_graph_artifact(request.session_id)  # 404 fast if the graph isn't built
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Session or graph not found. Build the graph first.") from exc

    async def runner(emit: jobs.Emit) -> None:
        counter = {"n": 0}

        def on_section(title: str, content_md: str) -> None:
            counter["n"] += 1
            emit({"type": "section", "data": {"index": counter["n"], "title": title, "content_md": content_md}})

        note = await notes_generate.generate_notes(request, on_section=on_section)
        emit({"type": "done", "data": {"note": note.model_dump(mode="json")}})

    return _job_stream(jobs.start(f"notes:{request.session_id}", runner))


@router.get("/notes/{session_id}/stream")
async def notes_stream(session_id: UUID) -> StreamingResponse:
    """Attach to an in-flight job (replay + live); else replay the saved note, else idle."""
    job = jobs.get(f"notes:{session_id}")
    if job is not None:
        return _job_stream(job)

    async def gen():
        try:
            note = local.load_note(session_id)
            yield _event({"type": "done", "data": {"note": note.model_dump(mode="json")}})
        except FileNotFoundError:
            yield _event({"type": "idle", "data": {}})

    return StreamingResponse(gen(), media_type="text/event-stream")


@router.get("/notes/{session_id}")
def get_notes(session_id: UUID) -> NoteDocument:
    try:
        return local.load_note(session_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="No generated notes for this session.") from exc


@router.delete("/notes/{session_id}")
def delete_notes(session_id: UUID) -> dict[str, bool]:
    try:
        local.load_session(session_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Session not found.") from exc
    local.delete_note(session_id)
    return {"ok": True}
