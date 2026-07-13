"""Process-local keyed locks for read-modify-write and expensive async operations.

The supported deployment intentionally runs one API worker; durable jobs cover
restart recovery, while these locks prevent duplicate work and lost JSON updates
inside that worker.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass


@dataclass
class _LockEntry:
    lock: asyncio.Lock
    users: int = 0


_LOCKS: dict[tuple[int, str], _LockEntry] = {}


@asynccontextmanager
async def keyed_lock(key: str):
    loop = asyncio.get_running_loop()
    lock_key = (id(loop), key)
    entry = _LOCKS.setdefault(lock_key, _LockEntry(asyncio.Lock()))
    entry.users += 1
    try:
        async with entry.lock:
            yield
    finally:
        entry.users -= 1
        if entry.users == 0 and _LOCKS.get(lock_key) is entry:
            _LOCKS.pop(lock_key, None)
