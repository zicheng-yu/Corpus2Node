from __future__ import annotations

import pytest

from corpus2node.llm import factory, store
from corpus2node.llm.credentials import (
    LLMSettings,
    ProviderCredential,
    ProviderKind,
    Purpose,
    PurposeBinding,
)
from corpus2node.llm.factory import LLMConfigError


def _settings_with(kind: ProviderKind) -> LLMSettings:
    cred = ProviderCredential(
        credential_id="c1",
        label="test",
        kind=kind,
        base_url="https://example.test/v1",
        api_key="sk-test-1234",
        default_model="m-default",
    )
    return LLMSettings(
        credentials=[cred],
        bindings={Purpose.graph: PurposeBinding(credential_id="c1", model="m-graph")},
    )


def test_store_roundtrip_persists_secret():
    store.save(_settings_with(ProviderKind.openai))
    store.reset_cache()
    loaded = store.load()
    assert loaded.credentials[0].api_key == "sk-test-1234"
    assert loaded.bindings[Purpose.graph].model == "m-graph"


def test_bootstrap_is_empty_without_env():
    loaded = store.load()  # tmp storage + env cleared by autouse fixture
    assert loaded.credentials == []
    assert loaded.bindings == {}


def test_critic_falls_back_to_graph():
    binding, credential = factory.resolve(Purpose.critic, _settings_with(ProviderKind.openai))
    assert binding.model == "m-graph"
    assert credential.credential_id == "c1"


def test_missing_binding_raises():
    with pytest.raises(LLMConfigError):
        factory.build_chat_model(Purpose.chat, value=LLMSettings())


def test_binding_without_model_uses_credential_default():
    value = _settings_with(ProviderKind.openai)
    value.bindings[Purpose.exam] = PurposeBinding(credential_id="c1")  # no model -> default
    binding, credential = factory.resolve(Purpose.exam, value)
    assert (binding.model or credential.default_model) == "m-default"


def test_build_openai_compatible_model():
    model = factory.build_chat_model(Purpose.graph, value=_settings_with(ProviderKind.openai))
    assert "OpenAI" in type(model).__name__


def test_build_anthropic_model():
    value = _settings_with(ProviderKind.anthropic)
    value.bindings[Purpose.chat] = PurposeBinding(credential_id="c1", model="claude-x")
    model = factory.build_chat_model(Purpose.chat, value=value)
    assert "Anthropic" in type(model).__name__


def _kimi_settings() -> LLMSettings:
    cred = ProviderCredential(
        credential_id="k1", label="Kimi", kind=ProviderKind.openai,
        base_url="https://api.moonshot.cn/v1", api_key="kimi-secret", default_model="kimi-k2.6",
    )
    return LLMSettings(credentials=[cred], bindings={Purpose.vision: PurposeBinding(credential_id="k1")})


def test_credential_params_resolves_vision_for_non_chat_clients():
    params = factory.credential_params(Purpose.vision, value=_kimi_settings(), default_timeout=99.0)
    assert params.base_url == "https://api.moonshot.cn/v1"
    assert params.api_key == "kimi-secret"
    assert params.model == "kimi-k2.6"
    assert params.timeout == 99.0  # falls back to default when the binding sets none


def test_credential_params_missing_purpose_raises():
    with pytest.raises(LLMConfigError):
        factory.credential_params(Purpose.vision, value=LLMSettings())


def test_load_auto_binds_vision_to_existing_kimi_credential():
    # Old registry (Kimi predates living in the registry): a Kimi-looking credential
    # with no vision binding gets auto-bound on load so multimodal ingest keeps working.
    cred = ProviderCredential(
        credential_id="k1", label="Kimi", kind=ProviderKind.openai,
        base_url="https://api.moonshot.cn/v1", api_key="x", default_model="kimi-k2.6",
    )
    store.save(LLMSettings(credentials=[cred]))  # no vision binding
    store.reset_cache()
    loaded = store.load()
    assert loaded.bindings[Purpose.vision].credential_id == "k1"
