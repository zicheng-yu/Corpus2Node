from __future__ import annotations

import hashlib
import json
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from corpus2node.accounts.database import get_db, session_factory
from corpus2node.accounts.dependencies import optional_principal, require_resource_access
from corpus2node.accounts.service import (
    AuthorizationError,
    QuotaError,
    enforce_quota,
    record_usage,
    register_resource,
    require_role,
)
from corpus2node.config import settings
from corpus2node.core.concurrency import keyed_lock
from corpus2node.core.types import WorkflowRunArtifact
from corpus2node.graph.critic import make_acritic
from corpus2node.graph.extract import make_astructured
from corpus2node.graph.workflow import load_valid_cached_graph, run_workflow, stream_workflow
from corpus2node.index.embeddings import get_embeddings
from corpus2node.llm import factory
from corpus2node.llm.credentials import Purpose
from corpus2node.llm.factory import LLMConfigError
from corpus2node.projects import schedule_project_refresh
from corpus2node.storage import local
from corpus2node.storage.run_artifact import load_run_artifact, run_artifact_path

router = APIRouter(prefix="/workflow", tags=["workflow"])


class WorkflowRunRequest(BaseModel):
    session_id: UUID
    force: bool = False


class WorkflowRunResponse(BaseModel):
    session_id: UUID
    status: str
    chunk_count: int
    concept_count: int
    relation_count: int
    cluster_count: int


@router.post("/run")
async def run(
    payload: WorkflowRunRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> WorkflowRunResponse:
    principal = optional_principal(request)
    resource = await require_resource_access(request, db, "session", str(payload.session_id))
    if principal is not None:
        try:
            require_role(principal, "member")
            await enforce_quota(db, principal, "ai_task")
        except AuthorizationError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except QuotaError as exc:
            raise HTTPException(status_code=429, detail=exc.detail()) from exc
    try:
        async with keyed_lock(f"workflow:{payload.session_id}"):
            graph = await run_workflow(payload.session_id, force=payload.force)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Session not found.") from exc
    except LLMConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if principal is not None:
        signature = hashlib.sha256(graph.provenance.model_dump_json().encode()).hexdigest()
        await register_resource(
            db,
            principal=principal,
            resource_type="session_graph",
            resource_key=str(payload.session_id),
            project_id=resource.project_id if resource else None,
            artifact_path=str(local.graph_path(payload.session_id)),
        )
        await register_resource(
            db,
            principal=principal,
            resource_type="workflow_run",
            resource_key=str(payload.session_id),
            project_id=resource.project_id if resource else None,
            artifact_path=str(run_artifact_path(payload.session_id)),
        )
        run_info = load_run_artifact(payload.session_id)
        await record_usage(
            db,
            principal,
            idempotency_key=f"workflow:{payload.session_id}:{signature}",
            metric="ai_task",
            purpose="graph",
            detail={
                "input_tokens": sum(value.prompt_tokens for value in run_info.nodes),
                "output_tokens": sum(value.completion_tokens for value in run_info.nodes),
                "total_tokens": run_info.total_tokens,
            },
        )
        await db.commit()
        if resource is not None and resource.project_id:
            schedule_project_refresh(resource.project_id, principal)
    session = local.load_session(payload.session_id)
    return WorkflowRunResponse(
        session_id=payload.session_id,
        status=session.status.value,
        chunk_count=session.stats.chunk_count,
        concept_count=len(graph.concepts),
        relation_count=len(graph.edges),
        cluster_count=len(graph.topic_clusters),
    )


@router.post("/stream")
async def stream(
    payload: WorkflowRunRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    principal = optional_principal(request)
    resource = await require_resource_access(request, db, "session", str(payload.session_id))
    if principal is not None:
        try:
            require_role(principal, "member")
            await enforce_quota(db, principal, "ai_task")
        except AuthorizationError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except QuotaError as exc:
            raise HTTPException(status_code=429, detail=exc.detail()) from exc
    # Embeddings are needed to validate cache provenance. LLMs are resolved lazily only
    # after a cache miss, so viewing a completed run does not require live credentials.
    try:
        session = local.load_session(payload.session_id)
        if not session.source_files:
            raise HTTPException(status_code=400, detail="Session has no source files to process.")
        embeddings = get_embeddings()
        cached = None if payload.force else load_valid_cached_graph(payload.session_id, embeddings)
        astructured = None
        acritic = None
        if cached is None:
            method = factory.structured_output_method(Purpose.graph)
            astructured = make_astructured(factory.build_chat_model(Purpose.graph), method=method)
            if settings.graph_critic_enabled:
                cmethod = factory.structured_output_method(Purpose.critic)
                acritic = make_acritic(factory.build_chat_model(Purpose.critic), method=cmethod)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Session not found.") from exc
    except LLMConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    async def event_source():
        succeeded = False
        async with keyed_lock(f"workflow:{payload.session_id}"):
            async for event in stream_workflow(
                payload.session_id,
                astructured=astructured,
                acritic=acritic,
                embeddings=embeddings,
                force=payload.force,
            ):
                if event.get("type") == "done":
                    succeeded = True
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        if succeeded and principal is not None:
            async with session_factory()() as usage_db:
                await register_resource(
                    usage_db,
                    principal=principal,
                    resource_type="session_graph",
                    resource_key=str(payload.session_id),
                    project_id=resource.project_id if resource else None,
                    artifact_path=str(local.graph_path(payload.session_id)),
                )
                await register_resource(
                    usage_db,
                    principal=principal,
                    resource_type="workflow_run",
                    resource_key=str(payload.session_id),
                    project_id=resource.project_id if resource else None,
                    artifact_path=str(run_artifact_path(payload.session_id)),
                )
                run_info = load_run_artifact(payload.session_id)
                await record_usage(
                    usage_db,
                    principal,
                    idempotency_key=f"workflow-stream:{payload.session_id}:{local.load_session(payload.session_id).updated_at.isoformat()}",
                    metric="ai_task",
                    purpose="graph",
                    detail={
                        "input_tokens": sum(value.prompt_tokens for value in run_info.nodes),
                        "output_tokens": sum(value.completion_tokens for value in run_info.nodes),
                        "total_tokens": run_info.total_tokens,
                    },
                )
                await usage_db.commit()
            if resource is not None and resource.project_id:
                schedule_project_refresh(resource.project_id, principal)

    return StreamingResponse(event_source(), media_type="text/event-stream")


@router.get("/{session_id}/run")
async def run_artifact(
    session_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> WorkflowRunArtifact:
    """The latest run's per-node observability (duration / tokens / repairs / errors)."""
    await require_resource_access(request, db, "session", str(session_id))
    try:
        return load_run_artifact(session_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="No workflow run recorded for this session.") from exc
