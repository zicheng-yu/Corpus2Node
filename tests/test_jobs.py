from __future__ import annotations

import asyncio

from corpus2node import jobs


def test_subscribe_streams_live_events_then_ends():
    async def main():
        async def runner(emit):
            emit({"type": "a"})
            await asyncio.sleep(0)
            emit({"type": "b"})

        job = jobs.start("k1", runner)
        return [event async for event in job.subscribe()]

    jobs.reset()
    events = asyncio.run(main())
    jobs.reset()
    assert [e["type"] for e in events] == ["a", "b"]


def test_attach_after_completion_replays_all():
    async def main():
        async def runner(emit):
            emit({"type": "x"})

        job = jobs.start("k2", runner)
        await job.task  # finished before we subscribe → must replay
        return job, [event async for event in job.subscribe()]

    jobs.reset()
    job, events = asyncio.run(main())
    jobs.reset()
    assert job.status == "done"
    assert [e["type"] for e in events] == ["x"]


def test_failure_emits_error_event_and_marks_status():
    async def main():
        async def runner(emit):
            emit({"type": "x"})
            raise RuntimeError("boom")

        job = jobs.start("k3", runner)
        await job.task
        return job, [event async for event in job.subscribe()]

    jobs.reset()
    job, events = asyncio.run(main())
    jobs.reset()
    assert job.status == "error"
    assert any(e["type"] == "error" for e in events)


def test_start_attaches_to_running_job_instead_of_duplicating():
    async def main():
        started = asyncio.Event()
        release = asyncio.Event()

        async def runner(emit):
            emit({"type": "first"})
            started.set()
            await release.wait()
            emit({"type": "second"})

        first = jobs.start("k4", runner)
        await started.wait()
        second = jobs.start("k4", runner)  # attaches, does not start a duplicate
        release.set()
        await first.task
        return first, second

    jobs.reset()
    first, second = asyncio.run(main())
    jobs.reset()
    assert first is second
    assert [e["type"] for e in first.events] == ["first", "second"]


def test_start_rejects_different_fingerprint_for_running_job():
    async def main():
        started = asyncio.Event()
        release = asyncio.Event()

        async def runner(emit):
            started.set()
            await release.wait()

        job = jobs.start("k5", runner, fingerprint="a")
        await started.wait()
        try:
            jobs.start("k5", runner, fingerprint="b")
            raise AssertionError("expected JobConflict")
        except jobs.JobConflict:
            pass
        release.set()
        await job.task

    jobs.reset()
    asyncio.run(main())
    jobs.reset()
