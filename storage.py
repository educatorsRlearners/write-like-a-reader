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
        conn.execute("PRAGMA journal_mode=WAL")
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
        conn.execute("""
            CREATE TABLE IF NOT EXISTS llm_calls (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                essay_id INTEGER NOT NULL REFERENCES essays(id),
                sentence_index INTEGER,
                sentence_count INTEGER NOT NULL DEFAULT 1,
                call_type TEXT NOT NULL CHECK (call_type IN ('questioner', 'checker')),
                status TEXT NOT NULL CHECK (status IN ('success', 'failed')),
                retries INTEGER NOT NULL DEFAULT 0,
                duration_ms INTEGER NOT NULL,
                prompt_tokens INTEGER,
                completion_tokens INTEGER,
                error_message TEXT,
                created_at TEXT NOT NULL
            )
            """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_llm_calls_essay_id ON llm_calls(essay_id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_llm_calls_call_type ON llm_calls(call_type)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_llm_calls_created_at ON llm_calls(created_at)"
        )
        conn.execute("""
            CREATE TABLE IF NOT EXISTS feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                essay_id INTEGER NOT NULL REFERENCES essays(id),
                sentence_index INTEGER NOT NULL,
                rating TEXT NOT NULL CHECK (rating IN ('good', 'bad')),
                created_at TEXT NOT NULL
            )
            """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_feedback_essay_id ON feedback(essay_id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_feedback_created_at ON feedback(created_at)"
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

        rowid = cursor.lastrowid

        assert rowid is not None

        return rowid


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


def save_llm_call(
    essay_id: int,
    sentence_index: int | None,
    sentence_count: int,
    call_type: str,
    status: str,
    retries: int,
    duration_ms: int,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
    error_message: str | None = None,
) -> None:
    """Persist one timing/outcome row for a single `generate_json()` call.

    Failures are the caller's responsibility to handle (fail open -- a
    timing-write error must never block a student from getting feedback).
    """
    init_db()
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(
            "INSERT INTO llm_calls "
            "(essay_id, sentence_index, sentence_count, call_type, status, retries, "
            "duration_ms, prompt_tokens, completion_tokens, error_message, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                essay_id,
                sentence_index,
                sentence_count,
                call_type,
                status,
                retries,
                duration_ms,
                prompt_tokens,
                completion_tokens,
                error_message,
                datetime.now(timezone.utc).isoformat(),
            ),
        )


def save_feedback(essay_id: int, sentence_index: int, rating: str) -> None:
    """Persist a thumbs-up/down vote on a sentence's flagged question-group.

    Append-only: re-voting inserts a new row rather than updating the
    existing one, so history is preserved. Failures are the caller's
    responsibility to handle (fail open -- a feedback-write error must
    never block the student from reading their flagged questions).
    """
    if rating not in ("good", "bad"):
        raise ValueError(f"invalid rating: {rating!r}")
    init_db()
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(
            "INSERT INTO feedback (essay_id, sentence_index, rating, created_at) VALUES (?, ?, ?, ?)",
            (essay_id, sentence_index, rating, datetime.now(timezone.utc).isoformat()),
        )
