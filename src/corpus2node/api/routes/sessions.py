"""Session + upload routes for the demo flow: create session -> upload sources -> workflow -> chat."""
from __future__ import annotations

import logging
import os
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel

from corpus2node.config import settings
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

    filename = local.safe_display_filename(file.filename or "upload")
    ext = Path(filename).suffix.lower()
    if ext not in adapters.SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type {ext!r}. Supported: {', '.join(sorted(adapters.SUPPORTED_EXTENSIONS))}.",
        )

    source_id = uuid4()
    try:
        path, size_bytes = await _store_upload(session_id, source_id, filename, file)
    finally:
        await file.close()
    if size_bytes == 0:
        path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    kind = adapters.kind_for(filename)
    source = SourceFile(
        source_id=source_id,
        kind=kind,
        filename=filename,
        content_type=file.content_type or "application/octet-stream",
        storage_path=str(path),
        size_bytes=size_bytes,
    )
    session.source_files.append(source)
    session.status = SessionStatus.uploaded
    session.updated_at = utcnow()
    local.save_session(session)
    logger.info("uploaded %s (%d bytes, kind=%s) -> session %s", filename, size_bytes, kind.value, session_id)

    return UploadResponse(session_id=session_id, source_id=source.source_id, kind=kind, status=session.status)


async def _store_upload(session_id: UUID, source_id: UUID, filename: str, file: UploadFile) -> tuple[Path, int]:
    path = local.upload_dir(session_id) / local.stored_upload_filename(source_id, filename)
    root = local.upload_dir(session_id).resolve()
    resolved = path.resolve()
    if root not in resolved.parents:
        raise HTTPException(status_code=400, detail="Invalid upload filename.")

    tmp = path.with_name(f".{path.name}.tmp")
    size = 0
    try:
        with tmp.open("wb") as handle:
            while chunk := await file.read(settings.upload_chunk_size):
                size += len(chunk)
                if size > settings.max_upload_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail=f"Uploaded file exceeds {settings.max_upload_bytes} bytes.",
                    )
                handle.write(chunk)
        os.replace(tmp, path)
    except Exception:
        tmp.unlink(missing_ok=True)
        path.unlink(missing_ok=True)
        raise
    return path, size
