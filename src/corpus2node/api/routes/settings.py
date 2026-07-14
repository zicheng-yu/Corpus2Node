from __future__ import annotations

import ipaddress
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from corpus2node.llm import factory, store
from corpus2node.config import settings
from corpus2node.llm.credentials import (
    LLMSettings,
    ProviderCredential,
    ProviderKind,
    Purpose,
    PurposeBinding,
)

def _platform_settings_only(request: Request) -> None:
    if settings.auth_mode != "accounts":
        return
    principal = getattr(request.state, "principal", None)
    if principal is None or not principal.is_platform_admin:
        raise HTTPException(status_code=403, detail="Platform administrator required.")


router = APIRouter(
    prefix="/settings/llm",
    tags=["settings"],
    dependencies=[Depends(_platform_settings_only)],
)


def _mask(api_key: str) -> str:
    if not api_key:
        return ""
    if len(api_key) <= 4:
        return "•" * len(api_key)
    return "••••" + api_key[-4:]


class CredentialView(BaseModel):
    credential_id: str
    label: str
    kind: ProviderKind
    base_url: str
    default_model: str
    has_key: bool
    api_key_preview: str
    num_ctx: int | None = None
    max_concurrency: int | None = None


class BindingView(BaseModel):
    purpose: Purpose
    credential_id: str
    model: str
    temperature: float | None = None
    max_output_tokens: int | None = None
    timeout_seconds: float | None = None
    resolved: bool


class LLMSettingsView(BaseModel):
    credentials: list[CredentialView]
    bindings: list[BindingView]
    purposes: list[str]


class CredentialUpsert(BaseModel):
    credential_id: str | None = None  # set => update; omit => create
    label: str
    kind: ProviderKind
    base_url: str = ""
    api_key: str = ""  # blank on update keeps the existing key
    default_model: str = ""
    num_ctx: int | None = None  # Ollama context window (local kinds)
    max_concurrency: int | None = None  # client-side batch cap (local kinds)


class BindingUpsert(BaseModel):
    credential_id: str
    model: str = ""
    temperature: float | None = None
    max_output_tokens: int | None = None
    timeout_seconds: float | None = None


def _view(value: LLMSettings) -> LLMSettingsView:
    credentials = [
        CredentialView(
            credential_id=c.credential_id,
            label=c.label,
            kind=c.kind,
            base_url=c.base_url,
            default_model=c.default_model,
            has_key=bool(c.api_key),
            api_key_preview=_mask(c.api_key),
            num_ctx=c.num_ctx,
            max_concurrency=c.max_concurrency,
        )
        for c in value.credentials
    ]
    bindings = [
        BindingView(
            purpose=purpose,
            credential_id=b.credential_id,
            model=b.model,
            temperature=b.temperature,
            max_output_tokens=b.max_output_tokens,
            timeout_seconds=b.timeout_seconds,
            resolved=value.credential(b.credential_id) is not None,
        )
        for purpose, b in value.bindings.items()
    ]
    return LLMSettingsView(credentials=credentials, bindings=bindings, purposes=[p.value for p in Purpose])


@router.get("")
def get_settings() -> LLMSettingsView:
    return _view(store.load())


@router.post("/credentials")
def upsert_credential(payload: CredentialUpsert) -> LLMSettingsView:
    _validate_base_url(payload.base_url, payload.kind)
    value = store.load()
    if payload.credential_id:
        existing = value.credential(payload.credential_id)
        if existing is None:
            raise HTTPException(status_code=404, detail=f"Credential '{payload.credential_id}' not found.")
        existing.label = payload.label
        existing.kind = payload.kind
        existing.base_url = payload.base_url
        existing.default_model = payload.default_model
        existing.num_ctx = payload.num_ctx
        existing.max_concurrency = payload.max_concurrency
        if payload.api_key:  # only overwrite the secret when a new one is supplied
            existing.api_key = payload.api_key
    else:
        value.credentials.append(
            ProviderCredential(
                label=payload.label,
                kind=payload.kind,
                base_url=payload.base_url,
                api_key=payload.api_key,
                default_model=payload.default_model,
                num_ctx=payload.num_ctx,
                max_concurrency=payload.max_concurrency,
            )
        )
    store.save(value)
    return _view(value)


@router.delete("/credentials/{credential_id}")
def delete_credential(credential_id: str) -> LLMSettingsView:
    value = store.load()
    if value.credential(credential_id) is None:
        raise HTTPException(status_code=404, detail=f"Credential '{credential_id}' not found.")
    value.credentials = [c for c in value.credentials if c.credential_id != credential_id]
    value.bindings = {p: b for p, b in value.bindings.items() if b.credential_id != credential_id}
    store.save(value)
    return _view(value)


@router.put("/bindings/{purpose}")
def set_binding(purpose: Purpose, payload: BindingUpsert) -> LLMSettingsView:
    value = store.load()
    if value.credential(payload.credential_id) is None:
        raise HTTPException(status_code=400, detail=f"Credential '{payload.credential_id}' not found.")
    value.bindings[purpose] = PurposeBinding(
        credential_id=payload.credential_id,
        model=payload.model,
        temperature=payload.temperature,
        max_output_tokens=payload.max_output_tokens,
        timeout_seconds=payload.timeout_seconds,
    )
    store.save(value)
    return _view(value)


@router.delete("/bindings/{purpose}")
def clear_binding(purpose: Purpose) -> LLMSettingsView:
    value = store.load()
    value.bindings.pop(purpose, None)
    store.save(value)
    return _view(value)


class ModelListRequest(BaseModel):
    """Either an existing credential (uses its stored key) or raw probe params."""

    credential_id: str | None = None
    kind: ProviderKind | None = None
    base_url: str = ""
    api_key: str = ""  # POST body so a raw key never lands in URLs/access logs


class ModelListView(BaseModel):
    models: list[str]
    error: str | None = None


def _fetch_models(credential: ProviderCredential, timeout: float = 5.0) -> list[str]:
    """List an endpoint's models: Ollama via /api/tags, everything else via /models."""
    if credential.kind == ProviderKind.ollama:
        base = factory.native_base_url(credential)
        response = httpx.get(f"{base}/api/tags", timeout=timeout)
        response.raise_for_status()
        names = [m.get("name", "") for m in response.json().get("models", [])]
    else:
        base = factory.openai_compat_base_url(credential)
        if not base:
            raise ValueError("该凭据没有 base_url，无法枚举模型。")
        headers = {}
        api_key = factory.effective_api_key(credential)
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        response = httpx.get(f"{base}/models", headers=headers, timeout=timeout)
        response.raise_for_status()
        names = [m.get("id", "") for m in response.json().get("data", [])]
    return sorted({name for name in names if name})


@router.post("/models")
def list_models(payload: ModelListRequest) -> ModelListView:
    """Probe an endpoint for its available models (for the settings model dropdown).

    Failures come back as ``error`` with a 200 so the UI can degrade to free-text
    model input instead of surfacing a request failure.
    """
    if payload.credential_id:
        credential = store.load().credential(payload.credential_id)
        if credential is None:
            raise HTTPException(status_code=404, detail=f"Credential '{payload.credential_id}' not found.")
    elif payload.kind is not None:
        if settings.app_env.lower() == "production":
            raise HTTPException(
                status_code=403,
                detail="生产环境只允许探测已保存的凭据，禁止任意 endpoint 探测。",
            )
        _validate_base_url(payload.base_url, payload.kind)
        credential = ProviderCredential(
            label="probe", kind=payload.kind, base_url=payload.base_url, api_key=payload.api_key
        )
    else:
        raise HTTPException(status_code=400, detail="Provide credential_id or kind.")
    try:
        return ModelListView(models=_fetch_models(credential))
    except httpx.ConnectError:
        target = factory.native_base_url(credential) or "(default)"
        return ModelListView(models=[], error=f"无法连接 {target} —— 本地服务未启动？")
    except Exception as exc:  # surfaces as UI hint, not a 5xx
        return ModelListView(models=[], error=str(exc))


def _validate_base_url(value: str, kind: ProviderKind) -> None:
    if not value.strip():
        return
    parsed = urlsplit(value)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise HTTPException(status_code=400, detail="base_url 必须是无内嵌凭据的 http(s) URL。")
    hostname = parsed.hostname.lower().rstrip(".")
    remote_provider = kind not in {ProviderKind.ollama, ProviderKind.lmstudio}
    if (
        settings.app_env.lower() == "production"
        and remote_provider
        and (hostname == "localhost" or hostname.endswith(".localhost"))
    ):
        raise HTTPException(status_code=400, detail="生产环境的远程提供商不能指向 loopback 地址。")
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        return
    if address.is_link_local or address.is_multicast or address.is_unspecified:
        raise HTTPException(status_code=400, detail="base_url 指向不允许的网络地址。")
    if (
        settings.app_env.lower() == "production"
        and address.is_loopback
        and remote_provider
    ):
        raise HTTPException(status_code=400, detail="生产环境的远程提供商不能指向 loopback 地址。")
