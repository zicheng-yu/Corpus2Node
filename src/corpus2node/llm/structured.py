"""Bind a chat model to a Pydantic schema, returning a mockable async caller.

Mirrors ``graph.extract.make_astructured`` so notes/exam generation share the same
seam shape (a ``(prompt) -> Awaitable[Schema]`` callable). Default ``json_mode``
works with OpenAI-compatible vendors regardless of thinking/reasoning mode; the
factory picks ``function_calling`` only for Anthropic.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TypeVar

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)

StructuredCaller = Callable[[str], Awaitable[T]]


def make_structured(model, schema: type[T], *, system: str, method: str = "json_mode") -> StructuredCaller[T]:
    """Bind ``model`` to structured ``schema`` output behind a single-arg async call."""
    structured = model.with_structured_output(schema, method=method)

    async def _call(prompt: str) -> T:
        return await structured.ainvoke([SystemMessage(content=system), HumanMessage(content=prompt)])

    return _call
