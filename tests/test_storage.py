import sqlite3
from dataclasses import dataclass

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
