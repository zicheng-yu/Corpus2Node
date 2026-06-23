from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from corpus2node.graph.workflow import run_workflow
from corpus2node.llm.factory import LLMConfigError
from corpus2node.storage import local

router = APIRouter(prefix="/workflow", tags=["workflow"])


class WorkflowRunRequest(BaseModel):
    session_id: UUID


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
        graph = await run_workflow(request.session_id)
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
