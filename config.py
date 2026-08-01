import os

from dotenv import load_dotenv

load_dotenv()

OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:3b")
OLLAMA_HOST = os.environ.get("OLLAMA_HOST")
OLLAMA_TIMEOUT = float(os.environ.get("OLLAMA_TIMEOUT", "60"))
MAX_WORDS = 1000
MAX_SENTENCES = 20
DB_PATH = os.environ.get("DB_PATH", "data/essays.db")
