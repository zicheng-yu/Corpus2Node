from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field

from corpus2node.core.clock import utcnow


class ProviderKind(str, Enum):
    """Wire protocol of a credential's endpoint. Both support a custom base_url."""

    openai = "openai"  # OpenAI-compatible (DeepSeek, Kimi, vLLM, OpenRouter, ...)
    anthropic = "anthropic"  # Anthropic-compatible


class Purpose(str, Enum):
    """A model slot the app needs. Each is bound to one credential + model."""

    graph = "graph"
    critic = "critic"
    chat = "chat"
    exam = "exam"
    vision = "vision"  # image / PDF / video ingestion (Kimi-style multimodal, openai SDK)
    embedding = "embedding"  # remote OpenAI-compatible embeddings (when embed_provider=openai_compatible)


# A purpose with no binding of its own reuses another's (critic reuses graph).
# vision/embedding have no fallback — they need their own (multimodal / embedding) endpoint.
PURPOSE_FALLBACK: dict[Purpose, Purpose] = {Purpose.critic: Purpose.graph}

# Purposes that drive chat/completion models (shown together in the UI as one group).
# vision + embedding are non-chat purposes resolved via factory.credential_params.
CHAT_PURPOSES: tuple[Purpose, ...] = (Purpose.graph, Purpose.chat, Purpose.critic, Purpose.exam)


def _new_credential_id() -> str:
    return f"cred-{uuid.uuid4().hex[:8]}"


class ProviderCredential(BaseModel):
    """A stashed API key + endpoint the user can reuse across purposes."""

    credential_id: str = Field(default_factory=_new_credential_id)
    label: str
    kind: ProviderKind
    base_url: str = ""
    api_key: str = ""
    default_model: str = ""
    created_at: datetime = Field(default_factory=utcnow)


class PurposeBinding(BaseModel):
    """Which credential + model + params a purpose uses."""

    credential_id: str
    model: str = ""
    temperature: float | None = None
    max_output_tokens: int | None = None
    timeout_seconds: float | None = None


class LLMSettings(BaseModel):
    """The full registry: stashed credentials + per-purpose bindings."""

    credentials: list[ProviderCredential] = Field(default_factory=list)
    bindings: dict[Purpose, PurposeBinding] = Field(default_factory=dict)
    updated_at: datetime = Field(default_factory=utcnow)

    def credential(self, credential_id: str) -> ProviderCredential | None:
        return next((c for c in self.credentials if c.credential_id == credential_id), None)
