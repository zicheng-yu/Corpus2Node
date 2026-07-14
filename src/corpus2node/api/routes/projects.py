from __future__ import annotations

from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from corpus2node.accounts.database import get_db
from corpus2node.accounts.dependencies import current_principal
from corpus2node.accounts.entitlements import resolve_entitlements
from corpus2node.accounts.models import ActivityEvent, Project, ProjectRevision, Resource
from corpus2node.accounts.schemas import ActivityEventView, Principal, ProjectRevisionView, ProjectView
from corpus2node.accounts.service import (
    AuthorizationError,
    QuotaError,
    add_activity,
    enforce_quota,
    ensure_writable,
    organization_for_principal,
    record_usage,
    register_resource,
    require_role,
)
from corpus2node.assistant import agent as chat_agent
from corpus2node.assistant.tools import ChatContext
from corpus2node import prompt_store
from corpus2node.core.clock import utcnow
from corpus2node.core.concurrency import keyed_lock
from corpus2node.core.types import (
    ChatContextItem,
    ChatDocument,
    ChatMessage,
    ChatResponse,
    CourseSessionView,
    GraphArtifact,
    GraphArtifactView,
)
from corpus2node.index.embeddings import EmbeddingProvenanceError, ensure_embedding_compatible, get_embeddings
from corpus2node.llm import factory
from corpus2node.llm.credentials import Purpose
from corpus2node.llm.factory import LLMConfigError
from corpus2node.projects import refresh_project, schedule_project_refresh
from corpus2node.scientific.schemas import ScientificReport
from corpus2node.storage import local

router = APIRouter(prefix="/projects", tags=["projects"])


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)
    kind: str = "general"


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)


class ProjectChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8000)
    context_items: list[ChatContextItem] = Field(default_factory=list)
    debug: bool = False


async def _project_or_404(db: AsyncSession, principal: Principal, project_id: str) -> Project:
    project = await db.get(Project, project_id)
    if project is None or project.organization_id != principal.organization_id or project.archived_at is not None:
        raise HTTPException(status_code=404, detail="Project not found.")
    return project


async def _view(db: AsyncSession, project: Project) -> ProjectView:
    count = int(
        await db.scalar(
            select(func.count()).select_from(Resource).where(
                Resource.project_id == project.project_id,
                Resource.resource_type == "session",
                Resource.status == "active",
            )
        )
        or 0
    )
    return ProjectView(
        project_id=project.project_id,
        organization_id=project.organization_id,
        name=project.name,
        description=project.description,
        kind=project.kind,
        latest_revision_id=project.latest_revision_id,
        created_at=project.created_at,
        updated_at=project.updated_at,
        session_count=count,
    )


def _revision_view(value: ProjectRevision) -> ProjectRevisionView:
    return ProjectRevisionView(
        revision_id=value.revision_id,
        project_id=value.project_id,
        revision_number=value.revision_number,
        status=value.status,
        source_session_ids=list(value.source_session_ids),
        contributor_user_ids=list(value.contributor_user_ids),
        scientific_report_id=value.scientific_report_id,
        summary=value.summary,
        model_fingerprint=value.model_fingerprint,
        error=value.error,
        created_at=value.created_at,
        completed_at=value.completed_at,
    )


async def _revision_or_404(
    db: AsyncSession, principal: Principal, project_id: str, revision_id: str | None = None
) -> tuple[Project, ProjectRevision]:
    project = await _project_or_404(db, principal, project_id)
    target_id = revision_id or project.latest_revision_id
    revision = await db.get(ProjectRevision, target_id) if target_id else None
    if revision is None or revision.project_id != project_id or revision.status != "ready":
        raise HTTPException(status_code=404, detail="Project revision not found.")
    return project, revision


@router.get("", response_model=list[ProjectView])
async def list_projects(
    principal: Principal = Depends(current_principal),
    db: AsyncSession = Depends(get_db),
) -> list[ProjectView]:
    if principal.organization_id is None:
        return []
    values = (
        await db.scalars(
            select(Project).where(
                Project.organization_id == principal.organization_id,
                Project.archived_at.is_(None),
            ).order_by(Project.updated_at.desc())
        )
    ).all()
    return [await _view(db, value) for value in values]


@router.post("", response_model=ProjectView)
async def create_project(
    payload: ProjectCreate,
    principal: Principal = Depends(current_principal),
    db: AsyncSession = Depends(get_db),
) -> ProjectView:
    try:
        require_role(principal, "admin")
        organization = await ensure_writable(db, principal)
    except AuthorizationError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    limit = int(resolve_entitlements(organization)["max_projects"])
    used = int(
        await db.scalar(
            select(func.count()).select_from(Project).where(
                Project.organization_id == organization.organization_id,
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
    if payload.kind not in {"general", "scientific"}:
        raise HTTPException(status_code=400, detail="Project kind must be general or scientific.")
    name = " ".join(payload.name.split()).strip()
    duplicate = await db.scalar(
        select(Project.project_id).where(
            Project.organization_id == organization.organization_id,
            Project.name == name,
            Project.archived_at.is_(None),
        )
    )
    if duplicate:
        raise HTTPException(status_code=409, detail="A project with this name already exists.")
    project = Project(
        organization_id=organization.organization_id,
        name=name,
        description=payload.description.strip(),
        kind=payload.kind,
        created_by_user_id=principal.user_id,
    )
    db.add(project)
    await db.flush()
    await add_activity(db, principal, "project.created", project_id=project.project_id, resource_type="project", resource_key=project.project_id, detail={"name": name})
    await db.commit()
    return await _view(db, project)


@router.get("/{project_id}", response_model=ProjectView)
async def get_project(
    project_id: str,
    principal: Principal = Depends(current_principal),
    db: AsyncSession = Depends(get_db),
) -> ProjectView:
    return await _view(db, await _project_or_404(db, principal, project_id))


@router.patch("/{project_id}", response_model=ProjectView)
async def update_project(
    project_id: str,
    payload: ProjectUpdate,
    principal: Principal = Depends(current_principal),
    db: AsyncSession = Depends(get_db),
) -> ProjectView:
    project = await _project_or_404(db, principal, project_id)
    try:
        require_role(principal, "admin")
        await ensure_writable(db, principal)
    except AuthorizationError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    if payload.name is not None:
        project.name = " ".join(payload.name.split()).strip()
    if payload.description is not None:
        project.description = payload.description.strip()
    await add_activity(db, principal, "project.updated", project_id=project_id, resource_type="project", resource_key=project_id)
    await db.commit()
    return await _view(db, project)


@router.get("/{project_id}/revisions", response_model=list[ProjectRevisionView])
async def list_revisions(
    project_id: str,
    principal: Principal = Depends(current_principal),
    db: AsyncSession = Depends(get_db),
) -> list[ProjectRevisionView]:
    await _project_or_404(db, principal, project_id)
    values = (
        await db.scalars(
            select(ProjectRevision)
            .where(ProjectRevision.project_id == project_id)
            .order_by(ProjectRevision.revision_number.desc())
        )
    ).all()
    return [_revision_view(value) for value in values]


@router.get("/{project_id}/activity", response_model=list[ActivityEventView])
async def list_activity(
    project_id: str,
    principal: Principal = Depends(current_principal),
    db: AsyncSession = Depends(get_db),
) -> list[ActivityEventView]:
    await _project_or_404(db, principal, project_id)
    organization = await organization_for_principal(db, principal)
    if not bool(resolve_entitlements(organization)["team_graph"]):
        return []
    values = (
        await db.scalars(
            select(ActivityEvent)
            .where(ActivityEvent.project_id == project_id)
            .order_by(ActivityEvent.created_at.desc())
            .limit(200)
        )
    ).all()
    return [
        ActivityEventView(
            event_id=value.event_id,
            actor_user_id=value.actor_user_id,
            action=value.action,
            resource_type=value.resource_type,
            resource_key=value.resource_key,
            detail=value.detail,
            created_at=value.created_at,
        )
        for value in values
    ]


@router.get("/{project_id}/sessions", response_model=list[CourseSessionView])
async def list_project_sessions(
    project_id: str,
    principal: Principal = Depends(current_principal),
    db: AsyncSession = Depends(get_db),
) -> list[CourseSessionView]:
    await _project_or_404(db, principal, project_id)
    resources = (
        await db.scalars(
            select(Resource).where(
                Resource.project_id == project_id,
                Resource.resource_type == "session",
                Resource.status == "active",
            ).order_by(Resource.created_at.desc())
        )
    ).all()
    result: list[CourseSessionView] = []
    for resource in resources:
        try:
            session = local.load_session(UUID(resource.resource_key))
        except (FileNotFoundError, ValueError):
            continue
        result.append(
            CourseSessionView.from_session(
                session,
                project_id=project_id,
                created_by_user_id=resource.owner_user_id,
                published_at=resource.created_at,
            )
        )
    return result


@router.get("/{project_id}/graph", response_model=GraphArtifactView)
async def get_latest_project_graph(
    project_id: str,
    principal: Principal = Depends(current_principal),
    db: AsyncSession = Depends(get_db),
) -> GraphArtifactView:
    _, revision = await _revision_or_404(db, principal, project_id)
    try:
        graph = GraphArtifact.model_validate_json(Path(revision.graph_artifact_path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=404, detail="Project graph not found.") from exc
    return GraphArtifactView.from_artifact(graph)


@router.get("/{project_id}/revisions/{revision_id}/graph", response_model=GraphArtifactView)
async def get_revision_graph(
    project_id: str,
    revision_id: str,
    principal: Principal = Depends(current_principal),
    db: AsyncSession = Depends(get_db),
) -> GraphArtifactView:
    _, revision = await _revision_or_404(db, principal, project_id, revision_id)
    try:
        graph = GraphArtifact.model_validate_json(Path(revision.graph_artifact_path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=404, detail="Project graph not found.") from exc
    return GraphArtifactView.from_artifact(graph)


@router.get("/{project_id}/scientific", response_model=ScientificReport)
async def get_latest_project_scientific_report(
    project_id: str,
    principal: Principal = Depends(current_principal),
    db: AsyncSession = Depends(get_db),
) -> ScientificReport:
    _, revision = await _revision_or_404(db, principal, project_id)
    if not revision.scientific_report_id:
        raise HTTPException(status_code=404, detail="Project scientific report not found.")
    try:
        return local.load_scientific_report(revision.scientific_report_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Project scientific report not found.") from exc


@router.post("/{project_id}/refresh", response_model=ProjectRevisionView)
async def refresh_project_now(
    project_id: str,
    principal: Principal = Depends(current_principal),
    db: AsyncSession = Depends(get_db),
) -> ProjectRevisionView:
    project = await _project_or_404(db, principal, project_id)
    try:
        require_role(principal, "member")
        await enforce_quota(db, principal, "ai_task")
        organization = await organization_for_principal(db, principal)
    except AuthorizationError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except QuotaError as exc:
        raise HTTPException(
            status_code=429,
            detail=exc.detail(),
        ) from exc
    if not bool(resolve_entitlements(organization)["team_graph"]):
        raise HTTPException(status_code=403, detail="Team project revisions are not included in this plan.")
    revision = await refresh_project(project.project_id, principal)
    if revision is None:
        raise HTTPException(status_code=409, detail="No graph-ready project sources are available.")
    return _revision_view(revision)


@router.delete("/{project_id}/sessions/{session_id}")
async def deactivate_project_session(
    project_id: str,
    session_id: UUID,
    principal: Principal = Depends(current_principal),
    db: AsyncSession = Depends(get_db),
) -> dict[str, bool]:
    await _project_or_404(db, principal, project_id)
    try:
        require_role(principal, "admin")
        await ensure_writable(db, principal)
    except AuthorizationError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    resource = await db.scalar(
        select(Resource).where(
            Resource.project_id == project_id,
            Resource.resource_type == "session",
            Resource.resource_key == str(session_id),
            Resource.status == "active",
        )
    )
    if resource is None:
        raise HTTPException(status_code=404, detail="Session not found.")
    resource.status = "archived"
    try:
        session = local.load_session(session_id)
        source_ids = [str(value.source_id) for value in session.source_files]
        source_resources = (
            await db.scalars(
                select(Resource).where(
                    Resource.project_id == project_id,
                    Resource.resource_type == "source",
                    Resource.resource_key.in_(source_ids),
                )
            )
        ).all()
        for source in source_resources:
            source.status = "archived"
    except FileNotFoundError:
        pass
    await add_activity(
        db,
        principal,
        "session.archived",
        project_id=project_id,
        resource_type="session",
        resource_key=str(session_id),
    )
    await db.commit()
    schedule_project_refresh(project_id, principal)
    return {"ok": True}


@router.delete("/{project_id}")
async def archive_project(
    project_id: str,
    principal: Principal = Depends(current_principal),
    db: AsyncSession = Depends(get_db),
) -> dict[str, bool]:
    project = await _project_or_404(db, principal, project_id)
    try:
        require_role(principal, "admin")
        await ensure_writable(db, principal)
    except AuthorizationError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    project.archived_at = utcnow()
    resources = (await db.scalars(select(Resource).where(Resource.project_id == project_id))).all()
    for resource in resources:
        resource.status = "archived"
    await add_activity(db, principal, "project.archived", project_id=project_id)
    await db.commit()
    return {"ok": True}


def _project_chat_owner(principal: Principal) -> str:
    return f"{principal.organization_id}/{principal.user_id}"


def _load_project_chat(project_id: str, owner_key: str) -> ChatDocument:
    chat_id = UUID(project_id)
    try:
        return local.load_chat(chat_id, owner_key)
    except FileNotFoundError:
        return ChatDocument(session_id=chat_id)


@router.get("/{project_id}/chat", response_model=ChatDocument)
async def get_project_chat(
    project_id: str,
    principal: Principal = Depends(current_principal),
    db: AsyncSession = Depends(get_db),
) -> ChatDocument:
    await _project_or_404(db, principal, project_id)
    return _load_project_chat(project_id, _project_chat_owner(principal))


@router.post("/{project_id}/chat", response_model=ChatResponse)
async def project_chat(
    project_id: str,
    payload: ProjectChatRequest,
    principal: Principal = Depends(current_principal),
    db: AsyncSession = Depends(get_db),
) -> ChatResponse:
    _, revision = await _revision_or_404(db, principal, project_id)
    try:
        require_role(principal, "member")
        await enforce_quota(db, principal, "chat_turn")
    except AuthorizationError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except QuotaError as exc:
        raise HTTPException(
            status_code=429,
            detail=exc.detail(),
        ) from exc
    try:
        graph = GraphArtifact.model_validate_json(Path(revision.graph_artifact_path).read_text(encoding="utf-8"))
        chunks = [
            chunk
            for session_id in revision.source_session_ids
            for artifact in local.list_ingest_artifacts(UUID(session_id))
            for chunk in artifact.chunks
        ]
        embeddings = get_embeddings()
        ensure_embedding_compatible(graph, embeddings)
        ctx = ChatContext(graph, chunks, embeddings)
        model = factory.build_chat_model(Purpose.chat)
        owner_key = _project_chat_owner(principal)
        async with keyed_lock(f"project-chat:{project_id}:{principal.user_id}"):
            chat = _load_project_chat(project_id, owner_key)
            with prompt_store.owner_context(owner_key):
                turn = await chat_agent.run_chat(payload.message, ctx, model=model, history=chat.messages)
            chat.messages.append(ChatMessage(role="user", content=payload.message, context_items=payload.context_items))
            assistant = ChatMessage(role="assistant", content=turn.answer, citations=turn.citations)
            chat.messages.append(assistant)
            chat.updated_at = utcnow()
            local.save_chat(chat, owner_key)
    except (FileNotFoundError, OSError) as exc:
        raise HTTPException(status_code=404, detail="Project graph not found.") from exc
    except LLMConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except EmbeddingProvenanceError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await register_resource(
        db,
        principal=principal,
        resource_type="chat",
        resource_key=f"project:{project_id}:{principal.user_id}",
        project_id=project_id,
        owner_user_id=principal.user_id,
        artifact_path=str(local.chat_path(UUID(project_id), owner_key)),
    )
    await record_usage(
        db,
        principal,
        idempotency_key=f"project-chat:{project_id}:{chat.updated_at.isoformat()}",
        metric="chat_turn",
        purpose="project_chat",
        detail={"input_chars": len(payload.message), "output_chars": len(turn.answer)},
    )
    await db.commit()
    return ChatResponse(
        chat=chat,
        assistant_message=assistant,
        citations=turn.citations,
        trace=turn.trace if payload.debug else [],
        subgraph=turn.subgraph,
    )
