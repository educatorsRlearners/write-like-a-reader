import os

DB_PATH = os.environ.get("DB_PATH", "data/essays.db")

EXAMPLE_DRAFT = (
    "Social media has changed the way people communicate. Many students use it "
    "every day. Some teachers think it is a distraction. The school board is "
    "considering a new policy. This would help students focus better by "
    "resisting the siren's call of social media."
)
MAX_SENTENCES = 20
MAX_WORDS = 1000
OLLAMA_HOST = os.environ.get("OLLAMA_HOST")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:3b")
OLLAMA_TIMEOUT = float(os.environ.get("OLLAMA_TIMEOUT", "60"))
APP_HOST = os.environ.get("APP_HOST", "127.0.0.1")
APP_PORT = int(os.environ.get("APP_PORT", "7860"))
DASHBOARD_HOST = os.environ.get("DASHBOARD_HOST", "127.0.0.1")
DASHBOARD_PORT = int(os.environ.get("DASHBOARD_PORT", "7861"))
