from __future__ import annotations

from datetime import datetime, timezone


def utcnow() -> datetime:
    """Naive UTC timestamp without the deprecated ``datetime.utcnow()``.

    Returns a tz-naive value to keep the existing artifact wire format
    (ISO strings without a ``+00:00`` offset) unchanged.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)
