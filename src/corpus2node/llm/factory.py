from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from langchain.chat_models import init_chat_model

from corpus2node.llm import store
from corpus2node.llm.credentials import (
    DEFAULT_BASE_URLS,
    LOCAL_DUMMY_KEY,
    LOCAL_KINDS,
    PURPOSE_FALLBACK,
    LLMSettings,
    ProviderCredential,
    ProviderKind,
    Purpose,
    PurposeBinding,
)

# Ollama's server default context (4096) silently truncates extraction prompts,
# so an explicit window is always sent (credential.num_ctx overrides).
OLLAMA_DEFAULT_NUM_CTX = 8192
# Local servers queue beyond their parallel slots; keep client-side batches modest
# by default so requests don't sit in deep queues (credential.max_concurrency overrides).
LOCAL_DEFAULT_CONCURRENCY = 4


class LLMConfigError(RuntimeError):
    """Raised when a purpose has no usable credential/model binding."""


def purpose_signature(purpose: Purpose, *, value: LLMSettings | None = None) -> str:
    """Return a secret-free fingerprint for the model configuration behind a purpose."""
    try:
        binding, credential = resolve(purpose, value or store.load())
    except LLMConfigError:
        return "unbound"
    model = binding.model or credential.default_model
    payload = {
        "kind": credential.kind.value,
        "base_url": native_base_url(credential),
        "model": model,
        "num_ctx": credential.num_ctx,
        "temperature": binding.temperature,
        "max_output_tokens": binding.max_output_tokens,
    }
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]
    return f"{credential.kind.value}:{model or 'unset'}:{digest}"


def native_base_url(credential: ProviderCredential) -> str:
    """The credential's endpoint with the kind default filled in (no /v1 coercion)."""
    return (credential.base_url or DEFAULT_BASE_URLS.get(credential.kind, "")).rstrip("/")


def openai_compat_base_url(credential: ProviderCredential) -> str:
    """The endpoint in OpenAI-compatible form (Ollama serves that API under /v1)."""
    base = native_base_url(credential)
    if credential.kind == ProviderKind.ollama and base and not base.endswith("/v1"):
        return f"{base}/v1"
    return base


def effective_api_key(credential: ProviderCredential) -> str:
    """The API key, substituting a dummy for keyless local servers (SDKs demand one)."""
    if credential.api_key:
        return credential.api_key
    return LOCAL_DUMMY_KEY if credential.kind in LOCAL_KINDS else ""


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
    OpenAI-compatible embeddings). ``base_url``/``api_key`` are normalized for
    OpenAI-compatible SDK use (Ollama's /v1, dummy key for keyless local servers);
    ``kind`` lets callers pick a native client instead."""

    base_url: str
    api_key: str
    model: str
    timeout: float | None = None
    kind: ProviderKind = ProviderKind.openai


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
        base_url=openai_compat_base_url(credential),
        api_key=effective_api_key(credential),
        model=model,
        timeout=timeout,
        kind=credential.kind,
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
    Ollama also gets ``json_mode``: measured on gemma4-e2b, its grammar-locked
    ``json_schema`` mode collapses the relations array to [] on the big extraction
    schema, while json_mode (still syntactically-valid JSON via format=json) follows
    the prompt's format example and extracts relations. LM Studio keeps
    ``json_schema`` — its documented structured-output path.
    """
    _, credential = resolve(purpose, value or store.load())
    if credential.kind == ProviderKind.anthropic:
        return "function_calling"
    if credential.kind == ProviderKind.lmstudio:
        return "json_schema"
    return "json_mode"


def concurrency_for(purpose: Purpose, default: int, *, value: LLMSettings | None = None) -> int:
    """Client-side concurrency for batch stages (extract/critic).

    Local providers default to a modest cap so a laptop server isn't flooded;
    ``credential.max_concurrency`` overrides in either direction. Falls back to
    ``default`` when the purpose isn't bound (the caller will fail with a clearer
    error at request time).
    """
    try:
        _, credential = resolve(purpose, value or store.load())
    except LLMConfigError:
        return max(1, default)
    if credential.max_concurrency:
        return max(1, credential.max_concurrency)
    if credential.kind in LOCAL_KINDS:
        return min(max(1, default), LOCAL_DEFAULT_CONCURRENCY)
    return max(1, default)


def build_chat_model(purpose: Purpose, *, value: LLMSettings | None = None, **overrides: Any):
    """Build a LangChain chat model for a purpose from the credential registry.

    OpenAI-compatible and Anthropic-compatible endpoints go through
    ``init_chat_model(model_provider=..., base_url=..., api_key=...)``. Local kinds:
    Ollama uses its native client (``model_provider="ollama"``) because only the
    native API takes ``num_ctx`` — the OpenAI-compat endpoint would silently run at
    the server default context; LM Studio *is* an OpenAI-compatible server, so it
    reuses the openai path with a dummy key. Pass ``value`` to build from an
    explicit registry (tests). Extra ``overrides`` (e.g. ``temperature``) win.
    """
    value = value or store.load()
    binding, credential = resolve(purpose, value)
    model = binding.model or credential.default_model
    if not model:
        raise LLMConfigError(
            f"No model set for purpose '{purpose.value}' (neither binding nor credential default)."
        )

    if credential.kind == ProviderKind.ollama:
        kwargs = {
            "model": model,
            "model_provider": "ollama",
            "base_url": native_base_url(credential),
            "num_ctx": credential.num_ctx or OLLAMA_DEFAULT_NUM_CTX,
            # Thinking off by default: measured ~5x faster on thinking-capable small
            # models (gemma4) at equal extraction quality; harmless for models
            # without thinking. Callers can override with reasoning=True.
            "reasoning": False,
        }
        if binding.temperature is not None:
            kwargs["temperature"] = binding.temperature
        if binding.max_output_tokens is not None:
            kwargs["num_predict"] = binding.max_output_tokens  # ChatOllama's max_tokens
        if binding.timeout_seconds is not None:
            kwargs["client_kwargs"] = {"timeout": binding.timeout_seconds}
        kwargs.update(overrides)
        return init_chat_model(**kwargs)

    provider = "openai" if credential.kind == ProviderKind.lmstudio else credential.kind.value
    kwargs = {"model": model, "model_provider": provider}
    base_url = openai_compat_base_url(credential)
    if base_url:
        kwargs["base_url"] = base_url
    api_key = effective_api_key(credential)
    if api_key:
        kwargs["api_key"] = api_key
    if binding.temperature is not None:
        kwargs["temperature"] = binding.temperature
    if binding.max_output_tokens is not None:
        kwargs["max_tokens"] = binding.max_output_tokens
    if binding.timeout_seconds is not None:
        kwargs["timeout"] = binding.timeout_seconds
    kwargs.update(overrides)
    return init_chat_model(**kwargs)
