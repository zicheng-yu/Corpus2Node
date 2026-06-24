"""WorkflowRunArtifact: per-node observability (duration / tokens / repairs / errors).

`RunRecorder.node()` is an async context manager each workflow node enters; it times
the node, captures chat-model token usage via LangChain's usage-metadata callback
(works through async + structured-output calls), and records any error. The assembled
artifact is persisted next to the other session artifacts.
"""
from __future__ import annotations

import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from langchain_core.callbacks import get_usage_metadata_callback

from corpus2node.core.clock import utcnow
from corpus2node.core.types import WorkflowNodeRun, WorkflowRunArtifact
from corpus2node.storage import local


class RunRecorder:
    def __init__(self, session_id: uuid.UUID) -> None:
        self.artifact = WorkflowRunArtifact(session_id=session_id)
        self._start = time.perf_counter()

    @asynccontextmanager
    async def node(self, name: str):
        run = WorkflowNodeRun(node=name)
        start = time.perf_counter()
        try:
            with get_usage_metadata_callback() as cb:
                yield run
            _apply_usage(run, cb.usage_metadata)
        except Exception as exc:
            run.status = "error"
            run.error = str(exc)
            run.duration_ms = round((time.perf_counter() - start) * 1000, 1)
            self.artifact.nodes.append(run)
            raise
        run.duration_ms = round((time.perf_counter() - start) * 1000, 1)
        self.artifact.nodes.append(run)

    def finalize(self, status: str, error: str | None = None) -> WorkflowRunArtifact:
        self.artifact.status = status
        self.artifact.error = error
        self.artifact.finished_at = utcnow()
        self.artifact.duration_ms = round((time.perf_counter() - self._start) * 1000, 1)
        self.artifact.total_tokens = sum(node.total_tokens for node in self.artifact.nodes)
        return self.artifact


def _apply_usage(run: WorkflowNodeRun, usage_metadata: dict) -> None:
    for usage in (usage_metadata or {}).values():
        run.prompt_tokens += int(usage.get("input_tokens", 0) or 0)
        run.completion_tokens += int(usage.get("output_tokens", 0) or 0)
        run.total_tokens += int(usage.get("total_tokens", 0) or 0)


def run_artifact_path(session_id: uuid.UUID) -> Path:
    return local.session_dir(session_id) / "workflow_run.json"


def save_run_artifact(artifact: WorkflowRunArtifact) -> Path:
    path = run_artifact_path(artifact.session_id)
    path.write_text(artifact.model_dump_json(indent=2), encoding="utf-8")
    return path


def load_run_artifact(session_id: uuid.UUID) -> WorkflowRunArtifact:
    return WorkflowRunArtifact.model_validate_json(run_artifact_path(session_id).read_text(encoding="utf-8"))
