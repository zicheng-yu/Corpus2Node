from __future__ import annotations

import json
from uuid import UUID

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

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
from corpus2node.storage import local
from corpus2node.storage.run_artifact import load_run_artifact

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
async def run(request: WorkflowRunRequest) -> WorkflowRunResponse:
    try:
        async with keyed_lock(f"workflow:{request.session_id}"):
            graph = await run_workflow(request.session_id, force=request.force)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Session not found.") from exc
    except LLMConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    session = local.load_session(request.session_id)
    return WorkflowRunResponse(
        session_id=request.session_id,
        status=session.status.value,
        chunk_count=session.stats.chunk_count,
        concept_count=len(graph.concepts),
        relation_count=len(graph.edges),
        cluster_count=len(graph.topic_clusters),
    )


@router.post("/stream")
async def stream(request: WorkflowRunRequest) -> StreamingResponse:
    # Embeddings are needed to validate cache provenance. LLMs are resolved lazily only
    # after a cache miss, so viewing a completed run does not require live credentials.
    try:
        session = local.load_session(request.session_id)
        if not session.source_files:
            raise HTTPException(status_code=400, detail="Session has no source files to process.")
        embeddings = get_embeddings()
        cached = None if request.force else load_valid_cached_graph(request.session_id, embeddings)
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
        async with keyed_lock(f"workflow:{request.session_id}"):
            async for event in stream_workflow(
                request.session_id,
                astructured=astructured,
                acritic=acritic,
                embeddings=embeddings,
                force=request.force,
            ):
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_source(), media_type="text/event-stream")


@router.get("/{session_id}/run")
def run_artifact(session_id: UUID) -> WorkflowRunArtifact:
    """The latest run's per-node observability (duration / tokens / repairs / errors)."""
    try:
        return load_run_artifact(session_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="No workflow run recorded for this session.") from exc
