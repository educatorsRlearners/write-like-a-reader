import os

from dotenv import load_dotenv

# Load a local .env file (if present) into the environment before reading any
# settings. Never overrides real env vars, and is a no-op when there's no .env.
# Provider API keys live there (e.g. OPENAI_API_KEY) and are picked up by each
# vendor SDK directly — see llm_providers.py.
load_dotenv()

DB_PATH = os.environ.get("DB_PATH", "data/essays.db")

EXAMPLE_DRAFT = (
    "Social media has changed the way people communicate. Many students use it "
    "every day. Some teachers think it is a distraction. The school board is "
    "considering a new policy. This would help students focus better by "
    "resisting the siren's call of social media."
)

# Limits
MAX_SENTENCES = 20
MAX_WORDS = 1000

# Ollama settings (kept as fallbacks for the generic LLM_* vars below so
# existing setups keep working unchanged).
OLLAMA_HOST = os.environ.get("OLLAMA_HOST")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:3b")
OLLAMA_TIMEOUT = float(os.environ.get("OLLAMA_TIMEOUT", "60"))

# LLM provider selection. LLM_PROVIDER picks the backend adapter in
# llm_providers.py; everything else is shared across providers. The default
# provider is "ollama" so the app runs fully local with no credentials.
LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "ollama").lower()
_is_ollama = LLM_PROVIDER == "ollama"
# The OLLAMA_* fallbacks only make sense for the ollama provider — a cloud
# provider must get its own LLM_MODEL / LLM_BASE_URL (or none at all).
LLM_MODEL = os.environ.get("LLM_MODEL") or (OLLAMA_MODEL if _is_ollama else None)
LLM_BASE_URL = os.environ.get("LLM_BASE_URL") or (OLLAMA_HOST if _is_ollama else None)
# API keys are NOT read here — each adapter reads its own provider-specific var
# (OPENAI_API_KEY / ANTHROPIC_API_KEY / DEEPSEEK_API_KEY) at construction time.
_llm_timeout = os.environ.get("LLM_TIMEOUT")
LLM_TIMEOUT = float(_llm_timeout) if _llm_timeout not in (None, "") else OLLAMA_TIMEOUT
# Max tokens to generate per call. Both calls are batched over the whole
# submission (~MAX_SENTENCES sentences), so this needs headroom for a large
# JSON array; too low truncates it into unparseable output.
LLM_MAX_TOKENS = int(os.environ.get("LLM_MAX_TOKENS", "4096"))
LLM_NUM_CTX = int(os.environ.get("LLM_NUM_CTX", "8192"))  # Ollama-only

# Environment settings
APP_HOST = os.environ.get("APP_HOST", "127.0.0.1")
APP_PORT = int(os.environ.get("APP_PORT", "7860"))
DASHBOARD_HOST = os.environ.get("DASHBOARD_HOST", "127.0.0.1")
DASHBOARD_PORT = int(os.environ.get("DASHBOARD_PORT", "7861"))
