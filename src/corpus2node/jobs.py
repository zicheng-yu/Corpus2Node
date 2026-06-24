"""Tiny in-memory async job registry for long generations (notes / exam).

Generation runs as a detached ``asyncio`` task so it keeps going even after the
HTTP request that started it disconnects — that's what lets the UI navigate away
and re-attach later to see progress (instead of a blank screen). Each job buffers
its emitted events so a late/returning subscriber gets a full replay, then live
updates, then an end marker.

Single event loop, single process: all mutations are synchronous and therefore
atomic with respect to each other, so no locks are needed. State is lost on server
restart (fine for this stage; the final artifact is always persisted to disk).
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable

logger = logging.getLogger(__name__)

Emit = Callable[[dict], None]
Runner = Callable[[Emit], Awaitable[None]]

_END: dict = {"__end__": True}
_JOBS: dict[str, "Job"] = {}


class Job:
    def __init__(self, key: str) -> None:
        self.key = key
        self.status = "running"  # running | done | error
        self.error: str | None = None
        self.events: list[dict] = []
        self._subs: set[asyncio.Queue] = set()
        self.task: asyncio.Task | None = None

    def emit(self, event: dict) -> None:
        self.events.append(event)
        for queue in self._subs:
            queue.put_nowait(event)

    def finish(self, status: str, error: str | None = None) -> None:
        self.status = status
        self.error = error
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
    return _JOBS.get(key)


def is_running(key: str) -> bool:
    job = _JOBS.get(key)
    return job is not None and job.status == "running"


def start(key: str, runner: Runner) -> Job:
    """Start ``runner`` as a detached task under ``key`` (or attach if already running)."""
    existing = _JOBS.get(key)
    if existing is not None and existing.status == "running":
        return existing  # don't launch a duplicate — the new subscriber attaches to it
    job = Job(key)
    _JOBS[key] = job

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
