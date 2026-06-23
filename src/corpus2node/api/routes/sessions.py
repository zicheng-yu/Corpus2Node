"""Minimal session + upload routes — the human entry point for the demo flow:
create session -> upload PDF -> /workflow/run -> /chat. Multimodal formats
(ppt/word/md/images) + their adapters are a planned follow-up batch.
"""
from __future__ import annotations

import logging
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel

from corpus2node.core.clock import utcnow
from corpus2node.core.types import CourseSession, SessionStatus, SourceFile, UploadResponse
from corpus2node.ingest import adapters
from corpus2node.storage import local

router = APIRouter(prefix="/sessions", tags=["sessions"])
logger = logging.getLogger("corpus2node.api.sessions")


class CreateSessionRequest(BaseModel):
    course_title: str
    lecture_title: str


@router.post("")
def create_session(request: CreateSessionRequest) -> CourseSession:
    session = CourseSession(
        course_title=request.course_title,
        lecture_title=request.lecture_title,
        status=SessionStatus.draft,
    )
    local.save_session(session)
    return session


@router.get("")
def list_sessions() -> list[CourseSession]:
    sessions: list[CourseSession] = []
    for session_id in local.list_session_ids():
        try:
            sessions.append(local.load_session(session_id))
        except Exception:
            continue
    return sessions


@router.get("/{session_id}")
def get_session(session_id: UUID) -> CourseSession:
    try:
        return local.load_session(session_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Session not found.") from exc


@router.delete("/{session_id}")
def delete_session(session_id: UUID) -> dict[str, bool]:
    try:
        local.load_session(session_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Session not found.") from exc
    local.delete_session(session_id)
    return {"ok": True}


@router.post("/{session_id}/sources")
async def upload_source(session_id: UUID, file: UploadFile = File(...)) -> UploadResponse:
    try:
        session = local.load_session(session_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Session not found.") from exc

    filename = file.filename or "upload"
    ext = Path(filename).suffix.lower()
    if ext not in adapters.SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unsupported file type {ext!r}. Supported: "
                f"{', '.join(sorted(adapters.SUPPORTED_EXTENSIONS))}（图片/音频稍后支持）."
            ),
        )

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")
    path = local.write_upload(session_id, filename, data)

    kind = adapters.kind_for(filename)
    source = SourceFile(
        kind=kind,
        filename=filename,
        content_type=file.content_type or "application/octet-stream",
        storage_path=str(path),
        size_bytes=len(data),
    )
    session.source_files.append(source)
    session.status = SessionStatus.uploaded
    session.updated_at = utcnow()
    local.save_session(session)
    logger.info("uploaded %s (%d bytes, kind=%s) -> session %s", filename, len(data), kind.value, session_id)

    return UploadResponse(session_id=session_id, source_id=source.source_id, kind=kind, status=session.status)
