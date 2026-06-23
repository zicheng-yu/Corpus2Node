from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from corpus2node.llm import store
from corpus2node.llm.credentials import (
    LLMSettings,
    ProviderCredential,
    ProviderKind,
    Purpose,
    PurposeBinding,
)

router = APIRouter(prefix="/settings/llm", tags=["settings"])


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
    value = store.load()
    if payload.credential_id:
        existing = value.credential(payload.credential_id)
        if existing is None:
            raise HTTPException(status_code=404, detail=f"Credential '{payload.credential_id}' not found.")
        existing.label = payload.label
        existing.kind = payload.kind
        existing.base_url = payload.base_url
        existing.default_model = payload.default_model
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
