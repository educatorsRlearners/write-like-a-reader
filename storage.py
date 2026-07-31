import logging
import os
import sqlite3
from datetime import datetime, timezone

import config

logger = logging.getLogger(__name__)

DB_PATH = config.DB_PATH


def init_db() -> None:
    dirname = os.path.dirname(DB_PATH)
    if dirname:
        os.makedirs(dirname, exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS essays (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                text TEXT NOT NULL,
                word_count INTEGER NOT NULL,
                created_at TEXT NOT NULL
            )
            """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS questions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                essay_id INTEGER NOT NULL REFERENCES essays(id),
                question_index INTEGER NOT NULL,
                text TEXT NOT NULL,
                shown INTEGER NOT NULL
            )
            """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_questions_essay_id ON questions(essay_id)"
        )


def save_essay(text: str) -> int:
    """Persist a submitted draft and return its row id.

    Failures are the caller's responsibility to handle (e.g. fail open so a
    storage error never blocks a student from getting feedback).
    """
    init_db()
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute(
            "INSERT INTO essays (text, word_count, created_at) VALUES (?, ?, ?)",
            (text, len(text.split()), datetime.now(timezone.utc).isoformat()),
        )
        return cursor.lastrowid


def save_questions(essay_id: int, records: list) -> None:
    """Persist the questions generated for an essay, in generation order.

    `records` items need `.text` and `.shown` attributes (e.g. `QuestionRecord`).
    List position becomes `question_index`. Failures are the caller's
    responsibility to handle (e.g. fail open).
    """
    init_db()
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.executemany(
            "INSERT INTO questions (essay_id, question_index, text, shown) VALUES (?, ?, ?, ?)",
            [(essay_id, i, r.text, int(r.shown)) for i, r in enumerate(records)],
        )
