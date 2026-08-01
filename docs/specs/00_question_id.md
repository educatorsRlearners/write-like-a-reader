# Spec: Stable `Question` ID

**Status: SUPERSEDED (Phase E revision).** Retired — kept for history, not
implemented. This spec existed solely so `01_feedback_capture.md` could key
feedback rows to individual questions. During review, the feedback UI's
per-question rating design was found unreasonable (up to ~40 ratings for a
10-sentence draft) and was redesigned to rate one sentence's question-group
at a time, keyed on `(essay_id, sentence_index)` instead of a question id.
With that change, nothing in the project needs a stable `Question.id`
anymore. `02_speed.md`'s `all_questions`/`attach_question_ids` addition
(added during the original Phase C integration fix to support this spec)
has been reverted accordingly. Do not implement anything below.

---

**Status:** Phase A — narrow, frozen deliverable. Spec only; no app code changes yet.
**Owner:** This spec (`00_question_id.md`) owns the `id` field on `Question` /
`QuestionRecord`, the `PipelineResult.all_questions` field, and the
`storage.save_questions` return contract, going forward. See "Ownership
contract" at the end.

## Problem

`Question` (in `models.py`) is a bare frozen dataclass with only `text: str`.
Nothing identifies a question across the app/storage boundary. The
`questions` table in `storage.py` already has an autoincrement `id` primary
key, assigned when `save_questions()` inserts rows — but that id is never
read back, so no in-memory `Question` object ever knows its own db id. A
future feedback UI (thumbs-up/down per question, Task 3's output-format
work building on top of it) needs a stable key to attach feedback to. We
should thread the real `questions.id` value through, not invent a second,
disconnected synthetic id.

## Why this is trickier than "just add a field"

`Question` is constructed in `pipeline._parse_questions()`, long before any
database row exists. The db id is only assigned later, in `app.get_feedback()`,
when `storage.save_questions()` runs an `INSERT`. So:

- `Question.id` must be nullable — `None` until (and unless) storage
  succeeds. The app already fails open on storage errors (see
  `get_feedback()`: `save_essay`/`save_questions` failures are logged and
  swallowed), so a permanently-`None` id for a given run is an expected,
  supported state, not an error case.
- Because `Question` is frozen, we cannot mutate an existing instance's `id`
  in place. Ids are "attached" by replacing objects (`dataclasses.replace`)
  or by index-assignment into the mutable `list[Question]` that a frozen
  `Annotation` holds (the `questions` field is a list — replacing its
  contents is fine even though `Annotation` itself is frozen).
- `result.question_log` (built for storage) and `result.annotations[*].questions`
  (built for the UI) are two different views over the *same* generation
  event, in `pipeline.run()`. To stamp real db ids onto the `Question`
  objects the UI renders, we need an index-aligned bridge between "row order
  inserted into `questions`" and "which `Annotation.questions` list that
  `Question` object lives in." That bridge doesn't exist today and is part
  of this spec.

## Dataclass diff (`models.py`)

```diff
 @dataclass(frozen=True)
 class Question:
+    id: int | None
     text: str


 @dataclass(frozen=True)
 class QuestionRecord:
+    id: int | None
     text: str
     shown: bool
```

Both default to `None` at construction (`Question(text=...)` becomes
`Question(id=None, text=...)`, or give `id` a `= None` default so existing
call sites in `pipeline._parse_questions` don't need to pass it explicitly).
`id`, once set, is the literal `questions.id` primary key value from sqlite
— no separate synthetic/UUID scheme.

`PipelineResult` gains one new field, populated in lockstep with
`question_log` (same loop, same order, one entry per generated question
regardless of shown/answered status):

```diff
 @dataclass
 class PipelineResult:
     text: str
     sentences: list[Sentence]
     annotations: list[Annotation] = field(default_factory=list)
     failed_rounds: list[int] = field(default_factory=list)
     question_log: list[QuestionRecord] = field(default_factory=list)
+    all_questions: list[Question] = field(default_factory=list)
```

`all_questions[i]` and `question_log[i]` describe the same question at the
same position — `all_questions` is what lets us find the original `Question`
object (the one possibly also living inside an `Annotation.questions` list)
once we know `question_log[i]`'s assigned db id.

## Flow: storage save → pipeline construction → models → app render

1. **`pipeline._parse_questions`** — unchanged in spirit; constructs
   `Question(text=item)` with `id` left at its `None` default. No id exists
   yet at this point.

2. **`pipeline.run`** — in the existing loop that builds `question_log`,
   also append the originating `Question` object to `result.all_questions`
   at the same index:

   ```diff
        shown_ids = {id(q) for q in unanswered}
        for q in questions:
            result.question_log.append(QuestionRecord(text=q.text, shown=id(q) in shown_ids))
   +        result.all_questions.append(q)
   ```

   `unanswered` questions are the *same objects* (by Python identity) as
   the ones appended into `Annotation.questions` a few lines later — this
   identity sharing is what makes step 4 possible without touching
   `Annotation`.

3. **`storage.save_questions`** — change its return type from `None` to
   `list[int]`: one assigned `questions.id` per input record, **in the same
   order as the input `records` list** (which is `result.question_log`,
   which is index-aligned with `result.all_questions`). Recommend inserting
   rows individually (rather than `executemany`) and collecting each
   `cursor.lastrowid`, so the returned ids are correct by construction
   rather than by an assumption that AUTOINCREMENT rowids stay contiguous
   within a transaction.

   ```diff
   -def save_questions(essay_id: int, records: list) -> None:
   +def save_questions(essay_id: int, records: list) -> list[int]:
        ...
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("PRAGMA foreign_keys = ON")
   -        conn.executemany(
   -            "INSERT INTO questions (essay_id, question_index, text, shown) VALUES (?, ?, ?, ?)",
   -            [(essay_id, i, r.text, int(r.shown)) for i, r in enumerate(records)],
   -        )
   +        ids = []
   +        for i, r in enumerate(records):
   +            cursor = conn.execute(
   +                "INSERT INTO questions (essay_id, question_index, text, shown) VALUES (?, ?, ?, ?)",
   +                (essay_id, i, r.text, int(r.shown)),
   +            )
   +            ids.append(cursor.lastrowid)
   +        return ids
   ```

4. **`app.get_feedback`** — after the existing `storage.save_questions(...)`
   call, use the returned ids to stamp both `question_log` and the live
   `Question` objects inside `result.annotations`, via a new helper
   (`pipeline.attach_question_ids(result, ids)` is the suggested home, since
   it needs `all_questions` / `question_log` internals):

   ```diff
        if essay_id is not None:
            try:
   -            storage.save_questions(essay_id, result.question_log)
   +            ids = storage.save_questions(essay_id, result.question_log)
   +            pipeline.attach_question_ids(result, ids)
            except Exception:
                logger.warning("Failed to save questions to storage", exc_info=True)
   ```

   `attach_question_ids` (new, in `pipeline.py`):
   - Zips `ids` with `result.all_questions` and `result.question_log`
     (all three are index-aligned).
   - Rebuilds each `QuestionRecord` via `dataclasses.replace(record, id=new_id)`
     and writes it back into `result.question_log[i]` (list is mutable even
     though `PipelineResult` fields hold frozen elements).
   - Builds an identity map `{id(original_question): new_id}` from
     `all_questions`, then walks `result.annotations`, replacing each
     `Annotation.questions[j]` with `dataclasses.replace(q, id=new_id)`
     in place (index-assignment into the list — `Annotation` itself is
     never reconstructed).

   This runs **before** `highlight.to_highlighted_text(result)` and before
   `result_state` is returned to Gradio, so every `Question` object that
   reaches `on_select` (around `app.py` lines 96–114 today) already carries
   its real db id whenever storage succeeded. If storage failed or
   `essay_id` is `None`, ids simply stay `None` — `on_select` keys off
   `q.text` today and is unaffected either way; a future feedback UI reading
   `q.id` must handle `None` (e.g. disable/hide the feedback control for
   that question) rather than assume it's always present.

## Ownership contract

This spec **owns**, going forward:
- `Question.id`, `QuestionRecord.id` (models.py)
- `PipelineResult.all_questions` (models.py)
- `storage.save_questions`'s return contract (`list[int]`, index-aligned with input)
- `pipeline.attach_question_ids` and the identity-based stamping it does

**Task 3 (output-format spec) must not modify any of the above.** It may
*read* `Question.id` (e.g. to key a feedback widget, to include in an export
format) and must treat `None` as a valid, expected value. If Task 3 needs
additional identifying information beyond what's listed here, it should
extend `Question`/`Annotation` with new fields rather than repurposing or
renaming `id`.

## Explicitly out of scope for this spec

- Any UI for collecting feedback (thumbs-up/down widgets, storage of
  feedback events) — that's the full feedback-capture spec (Phase B).
- Changing `on_select`'s rendering behavior.
- Backfilling ids for rows already in an existing sqlite db from before this
  change (pre-existing rows simply have `id`s that were never surfaced to
  the app layer; no migration needed since the column already exists).
