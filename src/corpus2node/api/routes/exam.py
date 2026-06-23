from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException

from corpus2node.core.types import ExamDocument, GenerateExamRequest
from corpus2node.exam import generate as exam_generate
from corpus2node.llm.factory import LLMConfigError
from corpus2node.storage import local

router = APIRouter(tags=["exam"])


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
