from __future__ import annotations

import asyncio

from corpus2node.core import concurrency


def test_keyed_lock_serializes_waiters_and_releases_registry():
    async def scenario() -> list[str]:
        events: list[str] = []

        async def worker(name: str) -> None:
            async with concurrency.keyed_lock("same-session"):
                events.append(f"{name}:start")
                await asyncio.sleep(0)
                events.append(f"{name}:end")

        await asyncio.gather(worker("first"), worker("second"))
        return events

    events = asyncio.run(scenario())
    assert events in (
        ["first:start", "first:end", "second:start", "second:end"],
        ["second:start", "second:end", "first:start", "first:end"],
    )
    assert concurrency._LOCKS == {}
