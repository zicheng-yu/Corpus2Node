"""Session + upload routes for the demo flow: create session -> upload sources -> workflow -> chat."""
from __future__ import annotations

import hashlib
import logging
import os
import re
import zipfile
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from corpus2node.accounts.database import get_db
from corpus2node.accounts.dependencies import optional_principal
from corpus2node.accounts.entitlements import resolve_entitlements
from corpus2node.accounts.models import Project, Resource
from corpus2node.accounts.schemas import Principal
from corpus2node.accounts.service import (
    AuthorizationError,
    add_activity,
    ensure_writable,
    organization_for_principal,
    register_resource,
    record_usage,
    require_role,
    resource_for_principal,
)
from corpus2node.config import settings
from corpus2node.core.clock import utcnow
from corpus2node.core.types import CourseSession, CourseSessionView, SessionStatus, SourceFile, SourceKind, UploadResponse
from corpus2node.ingest import adapters
from corpus2node.projects import schedule_project_refresh
from corpus2node.storage import local

router = APIRouter(prefix="/sessions", tags=["sessions"])
logger = logging.getLogger("corpus2node.api.sessions")


class CreateSessionRequest(BaseModel):
    course_title: str
    lecture_title: str
    project_id: str | None = None


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


def _session_view(session: CourseSession, resource: Resource | None = None) -> CourseSessionView:
    return CourseSessionView.from_session(
        session,
        project_id=resource.project_id if resource else None,
        created_by_user_id=resource.owner_user_id if resource else None,
        published_at=resource.created_at if resource else None,
    )


async def _session_resource(
    db: AsyncSession, principal: Principal | None, session_id: UUID
) -> Resource | None:
    if principal is None:
        return None
    resource = await resource_for_principal(db, principal, "session", str(session_id))
    if resource is None:
        raise HTTPException(status_code=404, detail="Session not found.")
    return resource


async def _resolve_project(
    db: AsyncSession, principal: Principal, project_id: str | None, course_title: str
) -> Project:
    if principal.organization_id is None:
        raise HTTPException(status_code=400, detail="An active organization is required.")
    if project_id:
        project = await db.get(Project, project_id)
        if project is None or project.organization_id != principal.organization_id or project.archived_at is not None:
            raise HTTPException(status_code=404, detail="Project not found.")
        return project
    project = await db.scalar(
        select(Project).where(
            Project.organization_id == principal.organization_id,
            Project.name == course_title,
            Project.archived_at.is_(None),
        )
    )
    if project is not None:
        return project
    try:
        require_role(principal, "admin")
    except AuthorizationError as exc:
        raise HTTPException(
            status_code=403,
            detail="Only organization administrators can create a new project.",
        ) from exc
    organization = await organization_for_principal(db, principal)
    limit = int(resolve_entitlements(organization)["max_projects"])
    used = int(
        await db.scalar(
            select(func.count()).select_from(Project).where(
                Project.organization_id == principal.organization_id,
                Project.archived_at.is_(None),
            )
        )
        or 0
    )
    if used >= limit:
        raise HTTPException(
            status_code=429,
            detail={
                "code": "quota_exceeded",
                "metric": "projects",
                "used": used,
                "limit": limit,
                "reset_at": None,
            },
        )
    project = Project(
        organization_id=principal.organization_id,
        name=course_title,
        kind="general",
        created_by_user_id=principal.user_id,
    )
    db.add(project)
    await db.flush()
    return project


@router.post("", response_model=CourseSessionView)
async def create_session(
    payload: CreateSessionRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> CourseSessionView:
    principal = optional_principal(request)
    course_title = _clean_title(payload.course_title, field_name="course_title")
    project = None
    if principal is not None:
        try:
            require_role(principal, "member")
            await ensure_writable(db, principal)
        except AuthorizationError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        project = await _resolve_project(db, principal, payload.project_id, course_title)
        course_title = project.name
    session = CourseSession(
        course_title=course_title,
        lecture_title=_clean_title(payload.lecture_title, field_name="lecture_title"),
        status=SessionStatus.draft,
    )
    local.save_session(session)
    resource = None
    if principal is not None:
        resource = await register_resource(
            db,
            principal=principal,
            resource_type="session",
            resource_key=str(session.session_id),
            project_id=project.project_id if project else None,
            owner_user_id=principal.user_id,
            artifact_path=str(local.session_path(session.session_id)),
        )
        await add_activity(
            db,
            principal,
            "session.created",
            project_id=resource.project_id,
            resource_type="session",
            resource_key=str(session.session_id),
            detail={"title": session.lecture_title},
        )
        await db.commit()
    return _session_view(session, resource)


@router.get("", response_model=list[CourseSessionView])
async def list_sessions(request: Request, db: AsyncSession = Depends(get_db)) -> list[CourseSessionView]:
    principal = optional_principal(request)
    resources: dict[str, Resource] = {}
    session_ids = local.list_session_ids()
    if principal is not None:
        values = (
            await db.scalars(
                select(Resource).where(
                    Resource.organization_id == principal.organization_id,
                    Resource.resource_type == "session",
                    Resource.status == "active",
                )
            )
        ).all()
        resources = {value.resource_key: value for value in values}
        session_ids = [UUID(value) for value in resources]
    sessions: list[CourseSessionView] = []
    for session_id in session_ids:
        try:
            session = local.load_session(session_id)
            sessions.append(_session_view(session, resources.get(str(session_id))))
        except Exception:
            continue
    return sessions


@router.patch("/course/rename", response_model=list[CourseSessionView])
async def rename_course(
    payload: RenameCourseRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> list[CourseSessionView]:
    principal = optional_principal(request)
    old_title = _clean_title(payload.old_course_title, field_name="old_course_title")
    new_title = _clean_title(payload.new_course_title, field_name="new_course_title")
    if principal is not None:
        try:
            require_role(principal, "admin")
            await ensure_writable(db, principal)
        except AuthorizationError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        resources = (
            await db.scalars(
                select(Resource).where(
                    Resource.organization_id == principal.organization_id,
                    Resource.resource_type == "session",
                    Resource.status == "active",
                )
            )
        ).all()
        sessions = [local.load_session(UUID(value.resource_key)) for value in resources]
    else:
        resources = []
        sessions = _load_all_sessions()
    target_sessions = [session for session in sessions if session.course_title == old_title]
    if not target_sessions:
        raise HTTPException(status_code=404, detail="Knowledge base not found.")
    if old_title == new_title:
        return [_session_view(value) for value in target_sessions]
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
    if principal is not None:
        project = await db.scalar(
            select(Project).where(
                Project.organization_id == principal.organization_id,
                Project.name == old_title,
                Project.archived_at.is_(None),
            )
        )
        if project is not None:
            project.name = new_title
        await db.commit()
    by_key = {value.resource_key: value for value in resources}
    return [_session_view(value, by_key.get(str(value.session_id))) for value in updated]


def _load_all_sessions() -> list[CourseSession]:
    sessions: list[CourseSession] = []
    for session_id in local.list_session_ids():
        try:
            sessions.append(local.load_session(session_id))
        except Exception:
            continue
    return sessions


@router.patch("/{session_id}", response_model=CourseSessionView)
async def rename_session(
    session_id: UUID,
    payload: RenameSessionRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> CourseSessionView:
    principal = optional_principal(request)
    resource = await _session_resource(db, principal, session_id)
    if principal is not None:
        try:
            require_role(principal, "member")
            await ensure_writable(db, principal)
        except AuthorizationError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
    try:
        session = local.load_session(session_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Session not found.") from exc

    session.lecture_title = _clean_title(payload.lecture_title, field_name="lecture_title")
    session.updated_at = utcnow()
    local.save_session(session)
    if principal is not None:
        await add_activity(db, principal, "session.renamed", project_id=resource.project_id if resource else None, resource_type="session", resource_key=str(session_id))
        await db.commit()
    return _session_view(session, resource)


@router.get("/{session_id}", response_model=CourseSessionView)
async def get_session(
    session_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> CourseSessionView:
    resource = await _session_resource(db, optional_principal(request), session_id)
    try:
        return _session_view(local.load_session(session_id), resource)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Session not found.") from exc


@router.delete("/{session_id}")
async def delete_session(
    session_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, bool]:
    principal = optional_principal(request)
    resource = await _session_resource(db, principal, session_id)
    try:
        local.load_session(session_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Session not found.") from exc
    if principal is None:
        local.delete_session(session_id)
    else:
        try:
            require_role(principal, "admin")
            await ensure_writable(db, principal)
        except AuthorizationError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        assert resource is not None
        resource.status = "archived"
        try:
            session = local.load_session(session_id)
            source_ids = [str(value.source_id) for value in session.source_files]
            source_resources = (
                await db.scalars(
                    select(Resource).where(
                        Resource.organization_id == principal.organization_id,
                        Resource.resource_type == "source",
                        Resource.resource_key.in_(source_ids),
                    )
                )
            ).all()
            for source_resource in source_resources:
                source_resource.status = "archived"
        except FileNotFoundError:
            pass
        await add_activity(db, principal, "session.archived", project_id=resource.project_id, resource_type="session", resource_key=str(session_id))
        await db.commit()
        if resource.project_id:
            schedule_project_refresh(resource.project_id, principal)
    return {"ok": True}


@router.post("/{session_id}/sources")
async def upload_source(
    session_id: UUID,
    request: Request,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
) -> UploadResponse:
    principal = optional_principal(request)
    resource = await _session_resource(db, principal, session_id)
    if principal is not None:
        try:
            require_role(principal, "member")
            organization = await ensure_writable(db, principal)
        except AuthorizationError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        entitlements = resolve_entitlements(organization)
        active_sources = int(
            await db.scalar(
                select(func.count()).select_from(Resource).where(
                    Resource.organization_id == principal.organization_id,
                    Resource.resource_type == "source",
                    Resource.status == "active",
                )
            )
            or 0
        )
        if active_sources >= int(entitlements["max_active_sources"]):
            raise HTTPException(
                status_code=429,
                detail={
                    "code": "quota_exceeded",
                    "metric": "active_sources",
                    "used": active_sources,
                    "limit": entitlements["max_active_sources"],
                    "reset_at": None,
                },
            )
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
    if principal is not None:
        storage_used = int(
            await db.scalar(
                select(func.coalesce(func.sum(Resource.size_bytes), 0)).where(
                    Resource.organization_id == principal.organization_id,
                    Resource.status == "active",
                )
            )
            or 0
        )
        storage_limit = int(entitlements["max_storage_bytes"])
        if storage_used + size_bytes > storage_limit:
            path.unlink(missing_ok=True)
            raise HTTPException(
                status_code=429,
                detail={
                    "code": "quota_exceeded",
                    "metric": "storage_bytes",
                    "used": storage_used,
                    "limit": storage_limit,
                    "reset_at": None,
                },
            )

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
    if principal is not None:
        source_resource = await register_resource(
            db,
            principal=principal,
            resource_type="source",
            resource_key=str(source.source_id),
            project_id=resource.project_id if resource else None,
            owner_user_id=principal.user_id,
            artifact_path=str(path),
            size_bytes=size_bytes,
        )
        await add_activity(
            db,
            principal,
            "source.uploaded",
            project_id=source_resource.project_id,
            resource_type="source",
            resource_key=str(source.source_id),
            detail={"filename": filename, "size_bytes": size_bytes, "session_id": str(session_id)},
        )
        await record_usage(
            db,
            principal,
            idempotency_key=f"source-storage:{source.source_id}",
            metric="storage_growth",
            quantity=size_bytes,
            purpose="upload",
            detail={"filename": filename, "session_id": str(session_id), "request_bytes": size_bytes},
        )
        await db.commit()
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
