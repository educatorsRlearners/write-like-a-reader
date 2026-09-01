import sqlite3
from dataclasses import dataclass

import pytest

import storage


@dataclass
class _FakeRecord:
    text: str
    shown: bool


def test_save_essay_creates_table_and_returns_id(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DB_PATH", str(tmp_path / "essays.db"))

    essay_id = storage.save_essay("Hello world.")

    assert essay_id == 1


def test_save_essay_increments_id_and_persists_rows(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DB_PATH", str(tmp_path / "essays.db"))

    first_id = storage.save_essay("First draft.")
    second_id = storage.save_essay("Second draft, a bit longer than the first.")

    assert first_id == 1
    assert second_id == 2

    with sqlite3.connect(storage.DB_PATH) as conn:
        rows = conn.execute("SELECT id, text, word_count FROM essays ORDER BY id").fetchall()

    assert rows == [
        (1, "First draft.", 2),
        (2, "Second draft, a bit longer than the first.", 8),
    ]


def test_save_essay_computes_word_count(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DB_PATH", str(tmp_path / "essays.db"))

    storage.save_essay("one two three four")

    with sqlite3.connect(storage.DB_PATH) as conn:
        (word_count,) = conn.execute("SELECT word_count FROM essays").fetchone()

    assert word_count == 4


def test_save_questions_persists_index_text_and_shown(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DB_PATH", str(tmp_path / "essays.db"))
    essay_id = storage.save_essay("Some draft.")

    storage.save_questions(
        essay_id,
        [
            _FakeRecord(text="Who did this?", shown=False),
            _FakeRecord(text="Why did it happen?", shown=True),
        ],
    )

    with sqlite3.connect(storage.DB_PATH) as conn:
        rows = conn.execute(
            "SELECT essay_id, question_index, text, shown FROM questions ORDER BY question_index"
        ).fetchall()

    assert rows == [
        (essay_id, 0, "Who did this?", 0),
        (essay_id, 1, "Why did it happen?", 1),
    ]


def test_save_questions_keeps_essays_separate(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DB_PATH", str(tmp_path / "essays.db"))
    essay_id_1 = storage.save_essay("First essay.")
    essay_id_2 = storage.save_essay("Second essay.")

    storage.save_questions(essay_id_1, [_FakeRecord(text="Q1?", shown=True)])
    storage.save_questions(essay_id_2, [_FakeRecord(text="Q2?", shown=False)])

    with sqlite3.connect(storage.DB_PATH) as conn:
        rows = conn.execute("SELECT essay_id, text FROM questions ORDER BY essay_id").fetchall()

    assert rows == [(essay_id_1, "Q1?"), (essay_id_2, "Q2?")]


def test_init_db_enables_wal_mode(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DB_PATH", str(tmp_path / "essays.db"))
    storage.init_db()

    with sqlite3.connect(storage.DB_PATH) as conn:
        (mode,) = conn.execute("PRAGMA journal_mode").fetchone()

    assert mode.lower() == "wal"


def test_save_llm_call_persists_batched_row(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DB_PATH", str(tmp_path / "essays.db"))
    essay_id = storage.save_essay("Some draft.")

    storage.save_llm_call(
        essay_id,
        None,
        3,
        "questioner",
        "success",
        1,
        1234,
        prompt_tokens=100,
        completion_tokens=50,
    )

    with sqlite3.connect(storage.DB_PATH) as conn:
        row = conn.execute(
            "SELECT essay_id, sentence_index, sentence_count, call_type, status, "
            "retries, duration_ms, prompt_tokens, completion_tokens, error_message "
            "FROM llm_calls"
        ).fetchone()

    assert row == (essay_id, None, 3, "questioner", "success", 1, 1234, 100, 50, None)


def test_save_llm_call_persists_provider_and_model(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DB_PATH", str(tmp_path / "essays.db"))
    essay_id = storage.save_essay("Some draft.")

    storage.save_llm_call(
        essay_id,
        None,
        3,
        "questioner",
        "success",
        0,
        1234,
        provider="ollama",
        model="qwen2.5:3b",
    )

    with sqlite3.connect(storage.DB_PATH) as conn:
        provider, model = conn.execute(
            "SELECT provider, model FROM llm_calls"
        ).fetchone()

    assert provider == "ollama"
    assert model == "qwen2.5:3b"


def test_save_llm_call_records_failure_with_error_message(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DB_PATH", str(tmp_path / "essays.db"))
    essay_id = storage.save_essay("Some draft.")

    storage.save_llm_call(
        essay_id, None, 5, "checker", "failed", 2, 999, error_message="backend unreachable"
    )

    with sqlite3.connect(storage.DB_PATH) as conn:
        status, error_message = conn.execute(
            "SELECT status, error_message FROM llm_calls"
        ).fetchone()

    assert status == "failed"
    assert error_message == "backend unreachable"


def test_save_llm_call_defaults_missing_sentence_count_column_not_required(tmp_path, monkeypatch):
    # Old-style per-sentence call: sentence_index set, sentence_count still explicit.
    monkeypatch.setattr(storage, "DB_PATH", str(tmp_path / "essays.db"))
    essay_id = storage.save_essay("Some draft.")

    storage.save_llm_call(essay_id, 2, 1, "questioner", "success", 0, 500)

    with sqlite3.connect(storage.DB_PATH) as conn:
        sentence_index, sentence_count = conn.execute(
            "SELECT sentence_index, sentence_count FROM llm_calls"
        ).fetchone()

    assert sentence_index == 2
    assert sentence_count == 1


def test_save_feedback_persists_rating(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DB_PATH", str(tmp_path / "essays.db"))
    essay_id = storage.save_essay("Some draft.")

    storage.save_feedback(essay_id, 0, "good")

    with sqlite3.connect(storage.DB_PATH) as conn:
        row = conn.execute(
            "SELECT essay_id, sentence_index, rating FROM feedback"
        ).fetchone()

    assert row == (essay_id, 0, "good")


def test_save_feedback_appends_rather_than_overwrites(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DB_PATH", str(tmp_path / "essays.db"))
    essay_id = storage.save_essay("Some draft.")

    storage.save_feedback(essay_id, 0, "good")
    storage.save_feedback(essay_id, 0, "bad")

    with sqlite3.connect(storage.DB_PATH) as conn:
        ratings = [
            r for (r,) in conn.execute(
                "SELECT rating FROM feedback ORDER BY id"
            ).fetchall()
        ]

    assert ratings == ["good", "bad"]


def test_save_feedback_rejects_invalid_rating(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DB_PATH", str(tmp_path / "essays.db"))
    essay_id = storage.save_essay("Some draft.")

    with pytest.raises(ValueError):
        storage.save_feedback(essay_id, 0, "meh")
