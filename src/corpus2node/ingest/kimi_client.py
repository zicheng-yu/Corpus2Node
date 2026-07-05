"""Shared client for Kimi-style multimodal ingestion (image / PDF / video).

Credentials come from the runtime registry's ``vision`` purpose (Settings → Models),
NOT from .env — so all model credentials live in one place. PDF file-extract only
needs the endpoint+key; image/video also need the model name.
"""
from __future__ import annotations

from typing import Any

from corpus2node.config import settings
from corpus2node.llm import factory
from corpus2node.llm.credentials import Purpose
from corpus2node.llm.factory import LLMConfigError

_NOT_CONFIGURED = (
    "多模态摄入（图片 / PDF / 视频）需要在「设置 → 模型」里把一个凭据绑定到 vision 用途"
    "（例如 Kimi：base_url=https://api.moonshot.cn/v1、api_key、模型 kimi-k2.6）。"
)


def vision_available() -> bool:
    return factory.purpose_available(Purpose.vision)


def vision_is_moonshot() -> bool:
    """True when the vision purpose resolves to a Moonshot/Kimi endpoint.

    Gates the Moonshot-only features: the Files API (PDF file-extract, ms:// video
    upload) and K2.6 request quirks (thinking off via extra_body, no sampling
    params). A local vision credential (Ollama/LM Studio VLM) takes the plain
    OpenAI-compatible paths instead.
    """
    try:
        params = factory.credential_params(Purpose.vision)
    except LLMConfigError:
        return False
    return "moonshot" in params.base_url.lower()


def vision_client(*, timeout: float | None = None) -> tuple[Any, str]:
    """Return (openai_client, model) for Kimi-style multimodal ingest from the registry.

    Raises a clear RuntimeError if the ``vision`` purpose is not bound. ``timeout``
    overrides the binding/infra default (e.g. videos need a long timeout).
    """
    try:
        params = factory.credential_params(Purpose.vision, default_timeout=settings.vision_timeout_seconds)
    except LLMConfigError as exc:
        raise RuntimeError(_NOT_CONFIGURED) from exc
    if not params.api_key:
        raise RuntimeError(_NOT_CONFIGURED)

    try:
        from openai import OpenAI
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("多模态摄入需要 `openai` 包。") from exc

    kwargs: dict[str, Any] = {
        "api_key": params.api_key,
        "timeout": timeout or params.timeout or settings.vision_timeout_seconds,
    }
    if params.base_url:
        kwargs["base_url"] = params.base_url
    return OpenAI(**kwargs), params.model
