from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException

from corpus2node.core.types import GenerateNotesRequest, NoteDocument
from corpus2node.llm.factory import LLMConfigError
from corpus2node.notes import generate as notes_generate
from corpus2node.storage import local

router = APIRouter(tags=["notes"])


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
