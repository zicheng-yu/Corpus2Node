"""Session + upload routes for the demo flow: create session -> upload sources -> workflow -> chat."""
from __future__ import annotations

import hashlib
import logging
import os
import re
import zipfile
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel

from corpus2node.config import settings
from corpus2node.core.clock import utcnow
from corpus2node.core.types import CourseSession, SessionStatus, SourceFile, SourceKind, UploadResponse
from corpus2node.ingest import adapters
from corpus2node.storage import local

router = APIRouter(prefix="/sessions", tags=["sessions"])
logger = logging.getLogger("corpus2node.api.sessions")


class CreateSessionRequest(BaseModel):
    course_title: str
    lecture_title: str


class RenameSessionRequest(BaseModel):
    lecture_title: str


class RenameCourseRequest(BaseModel):
    old_course_title: str
    new_course_title: str


def _clean_title(value: str, *, field_name: str) -> str:
    title = re.sub(r"\s+", " ", value).strip()
    if not title:
        raise HTTPException(status_code=400, detail=f"{field_name} cannot be empty.")
    if len(title) > 120:
        raise HTTPException(status_code=400, detail=f"{field_name} is too long.")
    return title


@router.post("")
def create_session(request: CreateSessionRequest) -> CourseSession:
    session = CourseSession(
        course_title=_clean_title(request.course_title, field_name="course_title"),
        lecture_title=_clean_title(request.lecture_title, field_name="lecture_title"),
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


@router.patch("/course/rename")
def rename_course(request: RenameCourseRequest) -> list[CourseSession]:
    old_title = _clean_title(request.old_course_title, field_name="old_course_title")
    new_title = _clean_title(request.new_course_title, field_name="new_course_title")
    sessions = _load_all_sessions()
    target_sessions = [session for session in sessions if session.course_title == old_title]
    if not target_sessions:
        raise HTTPException(status_code=404, detail="Knowledge base not found.")
    if old_title == new_title:
        return target_sessions
    if any(session.course_title == new_title for session in sessions):
        raise HTTPException(status_code=409, detail="A knowledge base with this name already exists.")

    old_virtual_title = f"{local.COURSE_GRAPH_LECTURE_PREFIX}{old_title}"
    new_virtual_title = f"{local.COURSE_GRAPH_LECTURE_PREFIX}{new_title}"
    now = utcnow()
    updated: list[CourseSession] = []
    for session in target_sessions:
        session.course_title = new_title
        if session.lecture_title == old_virtual_title:
            session.lecture_title = new_virtual_title
        session.updated_at = now
        local.save_session(session)
        updated.append(session)
    return updated


def _load_all_sessions() -> list[CourseSession]:
    sessions: list[CourseSession] = []
    for session_id in local.list_session_ids():
        try:
            sessions.append(local.load_session(session_id))
        except Exception:
            continue
    return sessions


@router.patch("/{session_id}")
def rename_session(session_id: UUID, request: RenameSessionRequest) -> CourseSession:
    try:
        session = local.load_session(session_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Session not found.") from exc

    session.lecture_title = _clean_title(request.lecture_title, field_name="lecture_title")
    session.updated_at = utcnow()
    local.save_session(session)
    return session


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

    kind = adapters.kind_for(filename)
    upload_limit = _upload_limit(kind)
    source_id = uuid4()
    try:
        path, size_bytes, content_sha256 = await _store_upload(
            session_id, source_id, filename, file, max_bytes=upload_limit
        )
    finally:
        await file.close()
    if size_bytes == 0:
        path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")
    try:
        _validate_upload_content(path, ext)
    except ValueError as exc:
        path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    source = SourceFile(
        source_id=source_id,
        kind=kind,
        filename=filename,
        content_type=file.content_type or "application/octet-stream",
        storage_path=str(path),
        size_bytes=size_bytes,
        content_sha256=content_sha256,
    )
    session.source_files.append(source)
    session.status = SessionStatus.uploaded
    session.updated_at = utcnow()
    local.save_session(session)
    logger.info("uploaded %s (%d bytes, kind=%s) -> session %s", filename, size_bytes, kind.value, session_id)

    return UploadResponse(session_id=session_id, source_id=source.source_id, kind=kind, status=session.status)


async def _store_upload(
    session_id: UUID,
    source_id: UUID,
    filename: str,
    file: UploadFile,
    *,
    max_bytes: int,
) -> tuple[Path, int, str]:
    path = local.upload_dir(session_id) / local.stored_upload_filename(source_id, filename)
    root = local.upload_dir(session_id).resolve()
    resolved = path.resolve()
    if root not in resolved.parents:
        raise HTTPException(status_code=400, detail="Invalid upload filename.")

    tmp = path.with_name(f".{path.name}.tmp")
    size = 0
    digest = hashlib.sha256()
    try:
        with tmp.open("wb") as handle:
            while chunk := await file.read(settings.upload_chunk_size):
                size += len(chunk)
                if size > max_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail=f"Uploaded file exceeds the {max_bytes}-byte limit for this format.",
                    )
                handle.write(chunk)
                digest.update(chunk)
        os.replace(tmp, path)
    except Exception:
        tmp.unlink(missing_ok=True)
        path.unlink(missing_ok=True)
        raise
    return path, size, digest.hexdigest()


def _upload_limit(kind: SourceKind) -> int:
    by_kind = {
        SourceKind.document: settings.max_document_upload_bytes,
        SourceKind.pdf: settings.max_pdf_upload_bytes,
        SourceKind.image: settings.max_image_upload_bytes,
    }
    return min(settings.max_upload_bytes, by_kind.get(kind, settings.max_upload_bytes))


def _validate_upload_content(path: Path, extension: str) -> None:
    with path.open("rb") as handle:
        prefix = handle.read(16)
    signatures = {
        ".pdf": (b"%PDF-",),
        ".png": (b"\x89PNG\r\n\x1a\n",),
        ".jpg": (b"\xff\xd8\xff",),
        ".jpeg": (b"\xff\xd8\xff",),
        ".gif": (b"GIF87a", b"GIF89a"),
        ".webp": (b"RIFF",),
        ".docx": (b"PK\x03\x04",),
        ".pptx": (b"PK\x03\x04",),
    }
    expected = signatures.get(extension)
    if expected and not any(prefix.startswith(value) for value in expected):
        raise ValueError(f"File content does not match the {extension} extension.")
    if extension == ".webp" and prefix[8:12] != b"WEBP":
        raise ValueError("File content does not match the .webp extension.")
    if extension in {".docx", ".pptx"}:
        try:
            with zipfile.ZipFile(path) as archive:
                members = archive.infolist()
                names = {item.filename for item in members}
                office_root = "word/" if extension == ".docx" else "ppt/"
                if "[Content_Types].xml" not in names or not any(
                    name.startswith(office_root) for name in names
                ):
                    raise ValueError(f"File content is not a valid {extension} document.")
                total = sum(item.file_size for item in members)
                if total > settings.max_archive_uncompressed_bytes:
                    raise ValueError("Office document expands beyond the configured safety limit.")
        except zipfile.BadZipFile as exc:
            raise ValueError("Office document is not a valid ZIP-based file.") from exc
