import importlib

import pytest

import config


@pytest.fixture
def reload_config(monkeypatch):
    """Reload config.py with a patched environment, then restore it."""

    def _reload(**env):
        for key, value in env.items():
            if value is None:
                monkeypatch.delenv(key, raising=False)
            else:
                monkeypatch.setenv(key, value)
        return importlib.reload(config)

    yield _reload
    importlib.reload(config)


def test_env_int_falls_back_on_unset_and_empty(reload_config):
    cfg = reload_config(APP_PORT=None, DASHBOARD_PORT="")
    assert cfg.APP_PORT == 7860
    assert cfg.DASHBOARD_PORT == 7861


def test_env_int_honors_a_real_value(reload_config):
    cfg = reload_config(APP_PORT="9000")
    assert cfg.APP_PORT == 9000


def test_llm_base_url_env_override_applies_to_any_provider(monkeypatch):
    monkeypatch.setenv("LLM_BASE_URL", "https://gateway.example/v1")
    assert config._llm_base_url("ollama") == "https://gateway.example/v1"
    assert config._llm_base_url("openai") == "https://gateway.example/v1"
    assert config._llm_base_url("grok") == "https://gateway.example/v1"


def test_llm_base_url_defaults_without_override(monkeypatch):
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    assert config._llm_base_url("ollama") == "http://localhost:11434"
    assert config._llm_base_url("openai") is None


def test_llm_model_defaults_per_provider(monkeypatch):
    """Setting only a provider is enough — a default model is filled in."""
    monkeypatch.setattr(config, "LLM_MODEL_OVERRIDE", None)
    assert set(config.DEFAULT_MODELS) == {
        "ollama", "openai", "anthropic", "deepseek", "grok"
    }
    for provider, model in config.DEFAULT_MODELS.items():
        assert config._resolve_model(provider) == model


def test_llm_model_override_wins_over_default(monkeypatch):
    monkeypatch.setattr(config, "LLM_MODEL_OVERRIDE", "my-model")
    assert config._resolve_model("anthropic") == "my-model"
    assert config._resolve_model("grok") == "my-model"


def test_llm_model_none_for_unknown_provider(monkeypatch):
    monkeypatch.setattr(config, "LLM_MODEL_OVERRIDE", None)
    assert config._resolve_model("bogus") is None
