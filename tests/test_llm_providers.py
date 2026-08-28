import sys
import types
from typing import ClassVar

import pytest

import config
import llm_providers
from llm_client import LLMError
from llm_providers import LLMResponse, get_provider


@pytest.fixture(autouse=True)
def reset_provider_cache():
    llm_providers._provider = None
    yield
    llm_providers._provider = None


@pytest.fixture(autouse=True)
def clear_api_keys(monkeypatch):
    """config.py runs load_dotenv() at import, so a real .env key could leak
    into the test process — strip all provider keys unless a test sets one."""
    for env_name in llm_providers.PROVIDER_API_KEY_ENV.values():
        monkeypatch.delenv(env_name, raising=False)


@pytest.fixture
def cfg(monkeypatch):
    """Set provider config and return a helper to tweak individual values."""

    def _set(**kwargs):
        for key, value in kwargs.items():
            monkeypatch.setattr(config, key, value)

    _set(
        LLM_PROVIDER="ollama",
        LLM_MODEL="test-model",
        LLM_BASE_URL=None,
        LLM_TIMEOUT=60.0,
        LLM_MAX_TOKENS=2048,
        LLM_NUM_CTX=8192,
    )
    return _set


def _fake_module(name, **attrs):
    mod = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(mod, key, value)
    return mod


class _FakeOpenAI:
    """Records constructor kwargs in the class attr `seen`."""

    seen: ClassVar[dict] = {}

    def __init__(self, **kw):
        type(self).seen = dict(kw)
        self.chat = types.SimpleNamespace(
            completions=types.SimpleNamespace(
                create=lambda **kw: _fake_openai_response('{"ok": 1}', 7, 3)
            )
        )


def _install_openai(monkeypatch, client_cls=_FakeOpenAI):
    monkeypatch.setitem(
        sys.modules, "openai", _fake_module("openai", OpenAI=client_cls)
    )


# --- dispatch -------------------------------------------------------------

def test_get_provider_dispatches_on_config(cfg, monkeypatch):
    cfg(LLM_PROVIDER="anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    monkeypatch.setitem(
        sys.modules,
        "anthropic",
        _fake_module("anthropic", Anthropic=lambda **kw: object()),
    )
    assert isinstance(get_provider(), llm_providers.AnthropicProvider)


def test_get_provider_unknown_raises_llm_error(cfg):
    cfg(LLM_PROVIDER="bogus")
    with pytest.raises(LLMError, match="Unknown LLM_PROVIDER"):
        get_provider()


def test_failed_construction_is_not_cached(cfg, monkeypatch):
    cfg(LLM_PROVIDER="openai")
    _install_openai(monkeypatch, client_cls=lambda **kw: object())
    with pytest.raises(LLMError):
        get_provider()
    # A later fixed config should recover (cache was not poisoned).
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    _install_openai(monkeypatch)
    assert isinstance(get_provider(), llm_providers.OpenAIProvider)


def test_vendor_exception_at_construction_becomes_llm_error_and_is_not_cached(
    cfg, monkeypatch
):
    def boom(**kw):
        raise RuntimeError("bad base_url")  # stand-in for a vendor SDK error

    cfg(LLM_PROVIDER="openai")
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    _install_openai(monkeypatch, client_cls=boom)
    with pytest.raises(LLMError, match="Could not initialize"):
        get_provider()
    # Not cached: a later working SDK recovers.
    _install_openai(monkeypatch)
    assert isinstance(get_provider(), llm_providers.OpenAIProvider)


def test_get_provider_is_cached(cfg, monkeypatch):
    calls = {"n": 0}

    class FakeClient:
        def __init__(self, **kw):
            calls["n"] += 1

    monkeypatch.setitem(sys.modules, "ollama", _fake_module("ollama", Client=FakeClient))
    get_provider()
    get_provider()
    assert calls["n"] == 1


# --- Ollama (no API key) -------------------------------------------------------

def test_ollama_maps_response(cfg, monkeypatch):
    class FakeClient:
        def __init__(self, **kw):
            pass

        def chat(self, **kw):
            return {
                "message": {"content": '{"ok": true}'},
                "prompt_eval_count": 11,
                "eval_count": 5,
            }

    monkeypatch.setitem(sys.modules, "ollama", _fake_module("ollama", Client=FakeClient))
    assert get_provider().complete("hi") == LLMResponse('{"ok": true}', 11, 5)


def test_ollama_missing_token_counts(cfg, monkeypatch):
    class FakeClient:
        def __init__(self, **kw):
            pass

        def chat(self, **kw):
            return {"message": {"content": "x"}}

    monkeypatch.setitem(sys.modules, "ollama", _fake_module("ollama", Client=FakeClient))
    assert get_provider().complete("hi") == LLMResponse("x", None, None)


# --- OpenAI / DeepSeek -------------------------------------------------------

def _fake_openai_response(content, prompt_tokens=None, completion_tokens=None):
    usage = types.SimpleNamespace(
        prompt_tokens=prompt_tokens, completion_tokens=completion_tokens
    )
    message = types.SimpleNamespace(content=content)
    choice = types.SimpleNamespace(message=message)
    return types.SimpleNamespace(choices=[choice], usage=usage)


def test_openai_maps_response_and_reads_openai_api_key(cfg, monkeypatch):
    cfg(LLM_PROVIDER="openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    _install_openai(monkeypatch)
    assert get_provider().complete("hi") == LLMResponse('{"ok": 1}', 7, 3)
    assert _FakeOpenAI.seen["api_key"] == "sk-test"
    assert _FakeOpenAI.seen["base_url"] is None


def test_openai_honors_explicit_base_url(cfg, monkeypatch):
    cfg(LLM_PROVIDER="openai", LLM_BASE_URL="https://groq.example/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    _install_openai(monkeypatch)
    get_provider().complete("hi")
    assert _FakeOpenAI.seen["base_url"] == "https://groq.example/v1"


def test_openai_requires_model(cfg, monkeypatch):
    cfg(LLM_PROVIDER="openai", LLM_MODEL=None)
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    _install_openai(monkeypatch, client_cls=lambda **kw: object())
    with pytest.raises(LLMError, match="requires a model name"):
        get_provider()


def test_openai_requires_openai_api_key(cfg, monkeypatch):
    cfg(LLM_PROVIDER="openai")
    _install_openai(monkeypatch, client_cls=lambda **kw: object())
    with pytest.raises(LLMError, match="OPENAI_API_KEY"):
        get_provider()


def test_openai_missing_package_raises_llm_error(cfg, monkeypatch):
    cfg(LLM_PROVIDER="openai")
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    monkeypatch.setitem(sys.modules, "openai", None)  # forces ImportError
    with pytest.raises(LLMError, match="openai package"):
        get_provider()


def test_deepseek_defaults_base_url_and_reads_deepseek_api_key(cfg, monkeypatch):
    cfg(LLM_PROVIDER="deepseek")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "ds-key")
    _install_openai(monkeypatch)
    get_provider().complete("hi")
    assert _FakeOpenAI.seen["base_url"] == llm_providers.DEEPSEEK_BASE_URL
    assert _FakeOpenAI.seen["api_key"] == "ds-key"


def test_deepseek_ignores_openai_api_key(cfg, monkeypatch):
    """DeepSeek must key off DEEPSEEK_API_KEY, not OPENAI_API_KEY."""
    cfg(LLM_PROVIDER="deepseek")
    monkeypatch.setenv("OPENAI_API_KEY", "not-this-one")
    _install_openai(monkeypatch, client_cls=lambda **kw: object())
    with pytest.raises(LLMError, match="DEEPSEEK_API_KEY"):
        get_provider()


# --- Anthropic -------------------------------------------------------------

def test_anthropic_maps_response(cfg, monkeypatch):
    class FakeClient:
        def __init__(self, **kw):
            block = types.SimpleNamespace(type="text", text='{"ok": true}')
            usage = types.SimpleNamespace(input_tokens=9, output_tokens=4)
            response = types.SimpleNamespace(content=[block], usage=usage)
            self.messages = types.SimpleNamespace(create=lambda **kw: response)

    cfg(LLM_PROVIDER="anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    monkeypatch.setitem(
        sys.modules, "anthropic", _fake_module("anthropic", Anthropic=FakeClient)
    )
    assert get_provider().complete("hi") == LLMResponse('{"ok": true}', 9, 4)


def test_anthropic_requires_anthropic_api_key(cfg, monkeypatch):
    cfg(LLM_PROVIDER="anthropic")
    monkeypatch.setitem(
        sys.modules,
        "anthropic",
        _fake_module("anthropic", Anthropic=lambda **kw: object()),
    )
    with pytest.raises(LLMError, match="ANTHROPIC_API_KEY"):
        get_provider()
