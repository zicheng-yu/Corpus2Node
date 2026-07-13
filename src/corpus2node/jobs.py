"""Async job registry with durable event replay for long-running generations.

Generation runs as a detached ``asyncio`` task so it keeps going even after the
HTTP request that started it disconnects — that's what lets the UI navigate away
and re-attach later to see progress (instead of a blank screen). Each job buffers
its emitted events so a late/returning subscriber gets a full replay, then live
updates, then an end marker.

The live task/subscriber set is process-local, while metadata and events are written
to the artifact store. After a restart, clients can still inspect/replay completed
work; a formerly-running job is marked interrupted instead of pretending to run.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path

from corpus2node.config import settings
from corpus2node.core.clock import utcnow
from corpus2node.storage import local

logger = logging.getLogger(__name__)

Emit = Callable[[dict], None]
Runner = Callable[[Emit], Awaitable[None]]

_END: dict = {"__end__": True}
_JOBS: dict[str, "Job"] = {}
_MAX_FINISHED_JOBS = 64
_MAX_PERSISTED_EVENTS = 20_000


class JobConflict(RuntimeError):
    """Raised when a running job exists for the same key but different parameters."""


class Job:
    def __init__(
        self,
        key: str,
        *,
        fingerprint: str = "",
        status: str = "running",
        error: str | None = None,
        events: list[dict] | None = None,
    ) -> None:
        self.key = key
        self.fingerprint = fingerprint
        self.status = status  # running | done | error
        self.error = error
        self.events = events or []
        self._subs: set[asyncio.Queue] = set()
        self.task: asyncio.Task | None = None

    def emit(self, event: dict) -> None:
        self.events.append(event)
        if len(self.events) > _MAX_PERSISTED_EVENTS:
            self.events = self.events[-_MAX_PERSISTED_EVENTS:]
        _persist(self)
        for queue in self._subs:
            queue.put_nowait(event)

    def finish(self, status: str, error: str | None = None) -> None:
        self.status = status
        self.error = error
        _persist(self)
        for queue in self._subs:
            queue.put_nowait(_END)

    async def subscribe(self) -> AsyncIterator[dict]:
        """Replay buffered events, then stream live ones until the job ends."""
        queue: asyncio.Queue = asyncio.Queue()
        for event in self.events:  # snapshot replay — sync, so emit/finish can't interleave
            queue.put_nowait(event)
        if self.status != "running":
            queue.put_nowait(_END)
        self._subs.add(queue)
        try:
            while True:
                event = await queue.get()
                if event is _END:
                    return
                yield event
        finally:
            self._subs.discard(queue)


def get(key: str) -> Job | None:
    job = _JOBS.get(key)
    if job is not None:
        return job
    job = _load(key)
    if job is None:
        return None
    if job.status == "running":
        job.status = "error"
        job.error = "Server restarted before the job finished. Start the operation again."
        job.events.append({"type": "error", "data": {"message": job.error}})
        _persist(job)
    _JOBS[key] = job
    return job


def is_running(key: str) -> bool:
    job = get(key)
    return job is not None and job.status == "running"


def start(key: str, runner: Runner, *, fingerprint: str = "") -> Job:
    """Start ``runner`` as a detached task under ``key`` (or attach if already running)."""
    existing = get(key)
    if existing is not None and existing.status == "running":
        if existing.fingerprint != fingerprint:
            raise JobConflict("A generation job is already running with different parameters.")
        return existing  # don't launch a duplicate — the new subscriber attaches to it
    _prune_finished()
    job = Job(key, fingerprint=fingerprint)
    _JOBS[key] = job
    _persist(job)

    async def _run() -> None:
        try:
            await runner(job.emit)
            job.finish("done")
        except Exception as exc:  # surface as a terminal stream event, then mark errored
            logger.exception("job %s failed", key)
            job.emit({"type": "error", "data": {"message": str(exc)}})
            job.finish("error", str(exc))

    job.task = asyncio.create_task(_run())
    return job


def reset() -> None:
    """Drop all jobs (tests / teardown)."""
    _JOBS.clear()


def _prune_finished() -> None:
    finished = [key for key, job in _JOBS.items() if job.status != "running"]
    overflow = len(finished) - _MAX_FINISHED_JOBS
    if overflow <= 0:
        return
    for key in finished[:overflow]:
        _JOBS.pop(key, None)


def _jobs_dir() -> Path:
    path = Path(settings.local_storage_path) / "jobs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _job_path(key: str) -> Path:
    digest = hashlib.sha256(key.encode()).hexdigest()
    return _jobs_dir() / f"{digest}.json"


def _persist(job: Job) -> None:
    payload = {
        "key": job.key,
        "fingerprint": job.fingerprint,
        "status": job.status,
        "error": job.error,
        "events": job.events,
        "updated_at": utcnow().isoformat(),
    }
    local.write_text_atomic(_job_path(job.key), json.dumps(payload, ensure_ascii=False))


def _load(key: str) -> Job | None:
    path = _job_path(key)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("key") != key:
            return None
        return Job(
            key,
            fingerprint=str(payload.get("fingerprint", "")),
            status=str(payload.get("status", "error")),
            error=payload.get("error"),
            events=list(payload.get("events", []))[-_MAX_PERSISTED_EVENTS:],
        )
    except (OSError, ValueError, TypeError):
        logger.warning("ignoring unreadable persisted job %s", path)
        return None
