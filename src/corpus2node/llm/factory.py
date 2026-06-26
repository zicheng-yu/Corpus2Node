from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from langchain.chat_models import init_chat_model

from corpus2node.llm import store
from corpus2node.llm.credentials import (
    PURPOSE_FALLBACK,
    LLMSettings,
    ProviderCredential,
    ProviderKind,
    Purpose,
    PurposeBinding,
)


class LLMConfigError(RuntimeError):
    """Raised when a purpose has no usable credential/model binding."""


def resolve(purpose: Purpose, value: LLMSettings) -> tuple[PurposeBinding, ProviderCredential]:
    """Resolve a purpose to its (binding, credential), applying fallbacks."""
    binding = value.bindings.get(purpose)
    if binding is None and purpose in PURPOSE_FALLBACK:
        binding = value.bindings.get(PURPOSE_FALLBACK[purpose])
    if binding is None:
        raise LLMConfigError(
            f"No LLM binding for purpose '{purpose.value}'. Add a credential and bind it via /settings/llm."
        )
    credential = value.credential(binding.credential_id)
    if credential is None:
        raise LLMConfigError(
            f"Binding for '{purpose.value}' references missing credential '{binding.credential_id}'."
        )
    return binding, credential


@dataclass(frozen=True)
class CredentialParams:
    """Raw connection params for non-LangChain clients (Kimi vision via the openai SDK,
    OpenAI-compatible embeddings)."""

    base_url: str
    api_key: str
    model: str
    timeout: float | None = None


def credential_params(
    purpose: Purpose, *, value: LLMSettings | None = None, default_timeout: float | None = None
) -> CredentialParams:
    """Resolve a purpose to raw (base_url, api_key, model, timeout) for non-chat clients."""
    value = value or store.load()
    binding, credential = resolve(purpose, value)
    model = binding.model or credential.default_model
    if not model:
        raise LLMConfigError(
            f"No model set for purpose '{purpose.value}' (neither binding nor credential default)."
        )
    timeout = binding.timeout_seconds if binding.timeout_seconds is not None else default_timeout
    return CredentialParams(
        base_url=credential.base_url, api_key=credential.api_key, model=model, timeout=timeout
    )


def purpose_available(purpose: Purpose, *, value: LLMSettings | None = None) -> bool:
    """True if the purpose resolves to a credential (used for clear pre-flight errors)."""
    try:
        resolve(purpose, value or store.load())
        return True
    except LLMConfigError:
        return False


def structured_output_method(purpose: Purpose, *, value: LLMSettings | None = None) -> str:
    """Pick a with_structured_output method by provider.

    OpenAI-compatible vendors (DeepSeek/Kimi/...) reliably support JSON mode but not
    always a forced tool_choice (thinking models reject it); Anthropic uses tools.
    """
    _, credential = resolve(purpose, value or store.load())
    return "function_calling" if credential.kind == ProviderKind.anthropic else "json_mode"


def build_chat_model(purpose: Purpose, *, value: LLMSettings | None = None, **overrides: Any):
    """Build a LangChain chat model for a purpose from the credential registry.

    OpenAI-compatible and Anthropic-compatible endpoints are both supported via
    ``init_chat_model(model_provider=..., base_url=..., api_key=...)``. Pass
    ``value`` to build from an explicit registry (tests); otherwise the persisted
    one is used. Extra ``overrides`` (e.g. ``temperature``) win over the binding.
    """
    value = value or store.load()
    binding, credential = resolve(purpose, value)
    model = binding.model or credential.default_model
    if not model:
        raise LLMConfigError(
            f"No model set for purpose '{purpose.value}' (neither binding nor credential default)."
        )

    kwargs: dict[str, Any] = {"model": model, "model_provider": credential.kind.value}
    if credential.base_url:
        kwargs["base_url"] = credential.base_url
    if credential.api_key:
        kwargs["api_key"] = credential.api_key
    if binding.temperature is not None:
        kwargs["temperature"] = binding.temperature
    if binding.max_output_tokens is not None:
        kwargs["max_tokens"] = binding.max_output_tokens
    if binding.timeout_seconds is not None:
        kwargs["timeout"] = binding.timeout_seconds
    kwargs.update(overrides)
    return init_chat_model(**kwargs)
