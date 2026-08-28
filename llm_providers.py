"""Pluggable LLM backends.

Each provider adapter wraps a vendor SDK and normalizes a single prompt-in,
text-out call to `LLMResponse`. `llm_client.py` talks only to `get_provider()`
and never imports a vendor SDK directly.

Selection is driven by `config.LLM_PROVIDER` ("ollama" by default). Vendor SDKs
other than `ollama` are optional dependencies, imported lazily inside each
adapter so the default local path needs nothing extra installed.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

import config
from errors import LLMError

DEEPSEEK_BASE_URL = "https://api.deepseek.com"

# Each cloud provider reads its own conventional API-key env var (loaded from
# .env by config.load_dotenv()). The vendor SDKs use these same names, so the
# key is picked up straight from the environment.
PROVIDER_API_KEY_ENV = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
}


@dataclass(frozen=True)
class LLMResponse:
    """Provider-neutral result of one model call."""

    text: str
    prompt_tokens: int | None
    completion_tokens: int | None


class Provider(Protocol):
    def complete(self, prompt: str) -> LLMResponse: ...


def _require_api_key(provider: str) -> str:
    env_name = PROVIDER_API_KEY_ENV.get(provider)
    if env_name is None:
        raise LLMError(f"No API-key env var configured for provider {provider!r}.")
    key = os.environ.get(env_name)
    if not key:
        raise LLMError(
            f"LLM_PROVIDER={provider!r} needs {env_name}. "
            "Add it to your .env file (see .env.example)."
        )
    return key


def _require_model(provider: str) -> str:
    if not (config.LLM_MODEL or "").strip():
        raise LLMError(
            f"LLM_PROVIDER={provider!r} requires a model name. Set LLM_MODEL."
        )
    return config.LLM_MODEL


class OllamaProvider:
    def __init__(self) -> None:
        try:
            import ollama
        except ImportError as exc:  # pragma: no cover - ollama is a core dep
            raise LLMError("The 'ollama' package is not installed.") from exc

        self._client = ollama.Client(
            host=config.LLM_BASE_URL, timeout=config.LLM_TIMEOUT
        )

    def complete(self, prompt: str) -> LLMResponse:
        resp = self._client.chat(
            model=config.LLM_MODEL,
            messages=[{"role": "user", "content": prompt}],
            options={
                "num_predict": config.LLM_MAX_TOKENS,
                "num_ctx": config.LLM_NUM_CTX,
            },
        )
        return LLMResponse(
            text=resp["message"]["content"],
            prompt_tokens=resp.get("prompt_eval_count"),
            completion_tokens=resp.get("eval_count"),
        )


class OpenAIProvider:
    #: Dict key in PROVIDER_API_KEY_ENV / _PROVIDERS; overridden by subclasses.
    provider_name: str = "openai"
    #: Overridden by DeepSeekProvider; None means "use the SDK default".
    default_base_url: str | None = None

    def __init__(self) -> None:
        try:
            import openai
        except ImportError as exc:
            raise LLMError(
                f"LLM_PROVIDER={self.provider_name!r} needs the openai package. "
                "Install it with: uv sync --extra openai"
            ) from exc

        self._model = _require_model(self.provider_name)
        self._client = openai.OpenAI(
            api_key=_require_api_key(self.provider_name),
            base_url=config.LLM_BASE_URL or self.default_base_url,
            timeout=config.LLM_TIMEOUT,
        )

    def complete(self, prompt: str) -> LLMResponse:
        # Note: some newer OpenAI models want `max_completion_tokens` instead
        # of `max_tokens`; override LLM_MODEL-specific handling here if needed.
        resp = self._client.chat.completions.create(
            model=self._model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=config.LLM_MAX_TOKENS,
        )
        usage = resp.usage
        return LLMResponse(
            text=resp.choices[0].message.content or "",
            prompt_tokens=getattr(usage, "prompt_tokens", None),
            completion_tokens=getattr(usage, "completion_tokens", None),
        )


class DeepSeekProvider(OpenAIProvider):
    provider_name = "deepseek"
    default_base_url = DEEPSEEK_BASE_URL


class AnthropicProvider:
    provider_name = "anthropic"

    def __init__(self) -> None:
        try:
            import anthropic
        except ImportError as exc:
            raise LLMError(
                "LLM_PROVIDER='anthropic' needs the anthropic package. "
                "Install it with: uv sync --extra anthropic"
            ) from exc

        self._model = _require_model(self.provider_name)
        self._client = anthropic.Anthropic(
            api_key=_require_api_key(self.provider_name),
            base_url=config.LLM_BASE_URL or None,
            timeout=config.LLM_TIMEOUT,
        )

    def complete(self, prompt: str) -> LLMResponse:
        resp = self._client.messages.create(
            model=self._model,
            max_tokens=config.LLM_MAX_TOKENS,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(
            b.text for b in resp.content if getattr(b, "type", None) == "text"
        )
        return LLMResponse(
            text=text,
            prompt_tokens=getattr(resp.usage, "input_tokens", None),
            completion_tokens=getattr(resp.usage, "output_tokens", None),
        )


# Values are zero-arg factories returning a Provider.
_PROVIDERS: dict[str, Callable[[], Provider]] = {
    "ollama": OllamaProvider,
    "openai": OpenAIProvider,
    "deepseek": DeepSeekProvider,
    "anthropic": AnthropicProvider,
}

_provider: Provider | None = None


def get_provider() -> Provider:
    """Return the configured provider adapter (constructed once, then cached).

    Every configuration problem (unknown provider, missing SDK, missing API
    key) is raised as `LLMError` so callers get uniform fail-open behavior.
    A failed construction is not cached, so a later fixed config recovers.
    """
    global _provider
    if _provider is None:
        try:
            factory = _PROVIDERS[config.LLM_PROVIDER]
        except KeyError:
            raise LLMError(
                f"Unknown LLM_PROVIDER {config.LLM_PROVIDER!r}. "
                f"Valid options: {', '.join(sorted(_PROVIDERS))}."
            ) from None
        try:
            _provider = factory()
        except LLMError:
            raise
        except Exception as exc:  # vendor SDK failed during construction
            raise LLMError(
                f"Could not initialize LLM_PROVIDER={config.LLM_PROVIDER!r}: "
                f"{type(exc).__name__}"
            ) from exc
    return _provider
