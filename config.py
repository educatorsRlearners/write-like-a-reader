import os

from dotenv import load_dotenv

# Load a local .env file (if present) into the environment. .env is ONLY for
# secrets — the provider API keys (OPENAI_API_KEY / ANTHROPIC_API_KEY /
# DEEPSEEK_API_KEY / GROK_API_KEY) — which must not be committed. Each vendor
# SDK reads its own key straight from the environment (see llm_providers.py).
# Everything else is configured in this file. load_dotenv() never overrides a
# real env var and is a no-op when there's no .env.
load_dotenv()


def _env_int(name: str, default: int) -> int:
    """int() an env var, falling back to `default` when unset OR empty."""
    return int(os.environ.get(name) or default)


# ==========================================================================
# Application configuration — edit these in code and commit them.
# ==========================================================================

# Which adapter in llm_providers.py to use. One of:
#
#   "ollama"    — local, no credentials. Talks to an Ollama server at
#                 LLM_BASE_URL (default http://localhost:11434).
#   "openai"    — OpenAI cloud API.    Secret in .env: OPENAI_API_KEY
#                 Install: uv sync --extra openai
#   "anthropic" — Anthropic cloud API. Secret in .env: ANTHROPIC_API_KEY
#                 Install: uv sync --extra anthropic
#   "deepseek"  — DeepSeek cloud API (OpenAI-compatible). Secret in .env:
#                 DEEPSEEK_API_KEY.  Install: uv sync --extra openai
#   "grok"      — xAI Grok API (OpenAI-compatible). Secret in .env:
#                 GROK_API_KEY (or XAI_API_KEY). Install: uv sync --extra openai
#
# An unknown value raises LLMError at first use, listing the valid options.
LLM_PROVIDER = "ollama"

# Each provider has a sensible default model, so setting a provider is enough.
DEFAULT_MODELS = {
    "ollama": "qwen2.5:3b",
    "openai": "gpt-4o-mini",
    "anthropic": "claude-sonnet-5",
    "deepseek": "deepseek-chat",
    "grok": "grok-4",
}

# Leave as None to use the provider's default; set a string to override it.
LLM_MODEL_OVERRIDE: str | None = None


def _resolve_model(provider: str) -> str | None:
    return LLM_MODEL_OVERRIDE or DEFAULT_MODELS.get(provider)


LLM_MODEL = _resolve_model(LLM_PROVIDER)

LLM_TIMEOUT = 60.0  # seconds per LLM call

# Max tokens to generate per call. Both calls are batched over the whole
# submission (~MAX_SENTENCES sentences), so this needs headroom for a large
# JSON array; too low truncates it into unparseable output.
LLM_MAX_TOKENS = 4096

LLM_NUM_CTX = 8192  # Ollama-only context window

# Soft input caps — warn but don't block. Sized so a whole submission fits in
# one questioner call and one checker call.
MAX_SENTENCES = 20
MAX_WORDS = 1000

EXAMPLE_DRAFT = (
    "Social media has changed the way people communicate. Many students use it "
    "every day. Some teachers think it is a distraction. The school board is "
    "considering a new policy. This would help students focus better by "
    "resisting the siren's call of social media."
)

# ==========================================================================
# Deployment bindings — where this process runs, not how the app behaves.
# These are the ONLY settings read from the environment: each has a default
# for local `uv run`, and docker-compose overrides them for the container.
# ==========================================================================


# The API endpoint. `LLM_BASE_URL` in the environment overrides it for any
# provider (docker-compose points it at the in-cluster http://ollama:11434;
# a cloud user can point it at an Azure/Groq/proxy gateway). With no override,
# ollama falls back to its local default and cloud providers use their SDK
# default (None).
def _llm_base_url(provider: str) -> str | None:
    override = os.environ.get("LLM_BASE_URL")
    if override:
        return override
    return "http://localhost:11434" if provider == "ollama" else None


LLM_BASE_URL = _llm_base_url(LLM_PROVIDER)

DB_PATH = os.environ.get("DB_PATH", "data/essays.db")

APP_HOST = os.environ.get("APP_HOST", "127.0.0.1")
APP_PORT = _env_int("APP_PORT", 7860)
DASHBOARD_HOST = os.environ.get("DASHBOARD_HOST", "127.0.0.1")
DASHBOARD_PORT = _env_int("DASHBOARD_PORT", 7861)
