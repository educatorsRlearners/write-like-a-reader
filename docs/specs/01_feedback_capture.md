# Spec: Feedback Capture (thumbs-up/down) + Dashboard

**Status:** Phase B — spec/design only, no app code changes yet.
**Does not depend on `docs/specs/00_question_id.md`.** That spec has been
marked SUPERSEDED — feedback no longer keys on individual questions (see
"Redesign: sentence-grain feedback" in the Reviewer sign-off at the end of
this doc for why). This spec makes no changes to `models.py` and reads no
field from it.
**Sibling (frozen, read-only for this spec):** `docs/specs/00_timing_schema.md`
(the `llm_calls` table). This spec's dashboard visualizes that table too, but
does not modify its schema or hook points.

## 1. UI hook: thumbs-up/down in `app.on_select`

### Grain: one rating per sentence's question-group, not per question

Feedback is captured at the same grain the reader already experiences a
selection at: **one rating for "the questions flagged for this sentence,"
not one rating per individual question.** A 10-sentence draft with 3-4
questions/sentence would otherwise require up to ~40 individual clicks to
rate every question — that's not what a "was this feedback useful"
signal should cost the student. One thumbs-up/down per sentence's
question-group is both the natural UX grain (the student is judging "did
this batch of questions feel right," not litigating each one) and a much
cheaper interaction (at most one click per annotated sentence).

### Component design: keep today's rendering, add one button pair

`app.on_select` (currently ~lines 96–114) keeps its existing single
`gr.Markdown` rendering, unchanged:

```python
lines = [f"- {q.text}" for q in annotation.questions]
return "\n".join(lines)
```

Below that markdown panel, add **one** `good_btn`/`bad_btn` pair (module
level, built once inside `gr.Blocks`, not per-question):

```python
detail_panel = gr.Markdown(label="Selected sentence's unanswered questions")
with gr.Row():
    good_btn = gr.Button("👍 Good questions", size="sm", scale=0)
    bad_btn = gr.Button("👎 Bad questions", size="sm", scale=0)
feedback_status_md = gr.Markdown(scale=0)
```

`on_select` needs to additionally expose which sentence is currently
selected, so the button click handlers (which fire later, independently)
know what they're rating. Add a small `gr.State` for that:

```python
current_selection_state = gr.State(None)  # (essay_id, sentence_index) | None
```

`on_select` becomes simpler than the per-question design it replaces — it
still renders `detail_panel` exactly as today, and now also returns the
`(essay_id, sentence_index)` pair for the selected annotation (or `None`
if the selection has no annotation / no unanswered questions):

```python
def on_select(state, evt: gr.SelectData):
    result, chunk_map = state
    if result is None or evt.index is None:
        return "", None
    idx = evt.index
    if isinstance(idx, (tuple, list)):
        idx = idx[0]
    if idx >= len(chunk_map):
        return "", None
    sentence_index = chunk_map[idx]
    if sentence_index is None:
        return "*(no question here)*", None
    annotation = next(
        (a for a in result.annotations if a.sentence_index == sentence_index), None
    )
    if annotation is None:
        return "*(this sentence has no unanswered questions)*", None
    lines = [f"- {q.text}" for q in annotation.questions]
    selection = (result.essay_id, sentence_index) if result.essay_id is not None else None
    return "\n".join(lines), selection
```

```python
highlighted.select(
    on_select,
    inputs=result_state,
    outputs=[detail_panel, current_selection_state],
)
```

(`result.essay_id` — `PipelineResult` needs the essay's db id available
to key feedback rows; see "Getting `essay_id` onto `PipelineResult`"
below. This is the one small addition this spec does need in
`pipeline.py`/`models.py`, in place of the `Question.id` machinery it no
longer needs.)

No per-question fixed row pool, no `MAX_QUESTIONS_PER_ANNOTATION`, no
overflow indicator — none of that machinery is needed once rating isn't
per-question. A sentence with 40 questions renders exactly as it does
today (one markdown blob, however long) and still costs at most one
click to rate.

### Getting `essay_id` onto `PipelineResult`

`app.get_feedback` already computes `essay_id = storage.save_essay(draft_text)`
before calling `pipeline.run(...)`, but `PipelineResult` doesn't currently
carry it — `essay_id` lives only in `get_feedback`'s local scope.
`02_speed.md` already adds the field this spec needs (for its own
`llm_calls` timing-row attribution) — this is that same field, reused,
not a second/separate addition:

```diff
 @dataclass
 class PipelineResult:
     text: str
     sentences: list[Sentence]
     annotations: list[Annotation] = field(default_factory=list)
     failed_rounds: list[int] = field(default_factory=list)
     question_log: list[QuestionRecord] = field(default_factory=list)
+    essay_id: int | None = None
```

This is **not** an open either-way choice between post-hoc mutation and
threading — it's threaded into `run()` at construction time, and
`02_speed.md` already did the work this spec needs to lean on:
`app.py`'s `essay_id = storage.save_essay(draft_text)` already runs
*before* `pipeline.run(...)` is called, so `essay_id` is known before
`PipelineResult` is ever constructed — there is no "after the fact"
moment the way there was for the old, now-superseded per-question id
(which genuinely could only be known after `storage.save_questions`
returned, post-construction). And `02_speed.md` has already added
exactly the parameter needed: `run(text: str, essay_id: int | None =
None, on_progress=None) -> PipelineResult`. This spec reuses that same
parameter — no new/separate mechanism. `pipeline.run` sets
`PipelineResult(..., essay_id=essay_id)` at construction, using the
`essay_id` it already receives as an argument (per `02_speed.md`, for its
own `llm_calls` timing-row attribution). `app.get_feedback`'s call site
becomes `pipeline.run(draft_text, essay_id=essay_id,
on_progress=on_progress)` — again, `02_speed.md`'s call-site change,
not a second one. `essay_id` stays `None` whenever `storage.save_essay`
failed (same fail-open path that already exists), and the click handlers
below treat a `None`/`None`-selection the same way section "Handling a
missing selection" describes.

This is a small, self-contained addition riding on `02_speed.md`'s
existing `essay_id` threading — it does not touch `Question`,
`QuestionRecord`, or any per-question field. `02_speed.md` adds the
`essay_id` *parameter* to `run()`'s signature (for its own `llm_calls`
attribution) but does not itself add an `essay_id` field to
`PipelineResult`, nor the line passing that parameter into the
`PipelineResult(...)` constructor call — those two things (the
`essay_id: int | None = None` field shown in the diff above, and the
one-line `PipelineResult(..., essay_id=essay_id)` addition at
`run()`'s construction site) are this spec's own hunks: small, additive,
non-conflicting with `02_speed.md`'s changes, but genuinely this spec's,
not already covered by it. See "Ownership notes" (`models.py`,
`pipeline.py`) for exactly which lines belong to which spec.

### Click handlers

Both buttons read `current_selection_state` and write one row via
`storage.save_feedback`:

```python
def _rate(selection, rating):
    if selection is None:
        return gr.update(value="*(select a flagged sentence first)*")
    essay_id, sentence_index = selection
    try:
        storage.save_feedback(essay_id, sentence_index, rating)
    except Exception:
        logger.warning("Failed to save feedback", exc_info=True)
        return gr.update(value="*(couldn't save — try again)*")
    return gr.update(value="Thanks!" if rating == "good" else "Noted.")

good_btn.click(
    lambda selection: _rate(selection, "good"),
    inputs=[current_selection_state],
    outputs=[feedback_status_md],
)
bad_btn.click(
    lambda selection: _rate(selection, "bad"),
    inputs=[current_selection_state],
    outputs=[feedback_status_md],
)
```

No `functools.partial`/positional-vs-keyword hazard here — each lambda
closes over a single literal string (`"good"`/`"bad"`) and takes exactly
one Gradio-supplied argument, so there's no argument-binding ambiguity to
get wrong.

### Handling a missing selection

If `essay_id` is `None` (storage failed) or nothing is currently
selected, `current_selection_state` is `None` and `_rate` shows
`*(select a flagged sentence first)*` / lets the storage failure surface
via the existing try/except — no button needs to be hidden or disabled
up front, since the failure mode is rare (storage write failure) and the
inline status message communicates it adequately without extra
visibility-toggling logic.

### Re-rating

Same as before: a second click on either button just inserts another
`feedback` row (see schema below) — append-only, no undo needed, no
extra state to track per sentence.

## 2. New `feedback` sqlite table

Follows the same conventions as `essays`/`questions` (`storage.py`) and the
sibling `llm_calls` table (`00_timing_schema.md`): `INTEGER PRIMARY KEY
AUTOINCREMENT`, `FOREIGN KEY` via `REFERENCES`, ISO 8601 UTC string
timestamps via `datetime.now(timezone.utc).isoformat()`.

```sql
CREATE TABLE IF NOT EXISTS feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    essay_id INTEGER NOT NULL REFERENCES essays(id),
    sentence_index INTEGER NOT NULL,
    rating TEXT NOT NULL CHECK (rating IN ('good', 'bad')),
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_feedback_essay_id ON feedback(essay_id);
CREATE INDEX IF NOT EXISTS idx_feedback_created_at ON feedback(created_at);
```

Keyed on `(essay_id, sentence_index)` — the same pair `llm_calls` already
uses to identify "which round of the pipeline" a row belongs to (see
`00_timing_schema.md`'s `sentence_index` column note: "matches the `i`
loop index in `pipeline.run()`"). No FK to `questions(id)` — this table no
longer references individual questions at all, since a rating covers the
whole question-group for that sentence, not one question.

### Column notes

- **`id`** — feedback event id.
- **`essay_id`** — FK to `essays(id)`, same pattern as `questions.essay_id`
  and `llm_calls.essay_id`.
- **`sentence_index`** — which sentence's question-group this rating
  covers, same 0-based indexing as `Annotation.sentence_index` /
  `llm_calls.sentence_index`. Not a FK (there's no `sentences` table —
  sentences aren't persisted independently, same as `llm_calls`' own
  `sentence_index` column).
- **`rating`** — `'good'` or `'bad'`, `CHECK`-enforced (same idiom as
  `llm_calls.call_type`/`status`). No neutral/skip value in this phase —
  a sentence the student doesn't rate simply has no `feedback` row, which
  is itself meaningful (unrated, not neutral).
- **`created_at`** — vote timestamp, same clock convention as the rest of
  `storage.py`.

### One row per rating action, on `(essay_id, sentence_index)` (upsert-free by design)

`feedback` is append-only: every click inserts a new row, keyed on
`(essay_id, sentence_index)` rather than on an individual question. This
was a deliberate choice over one-row-per-question:
- **Clean dashboard counts.** One click = one row, full stop. A
  one-row-per-question design would have made `COUNT(*)` in the dashboard
  skewed by how many questions happened to be in a given sentence's
  group (a sentence with 6 questions would contribute 6x the weight of a
  sentence with 1, for what was actually a single "yes, good" decision
  from the student) — this schema avoids that entirely.
- Keeps `save_feedback` a single `INSERT`, matching `save_essay`'s and
  `save_questions`'s simplicity — no read-before-write, no race between
  concurrent app instances.
- Preserves a full history (a student who flip-flops good→bad→good on the
  same sentence is itself a signal, not noise to discard) — useful for
  the dashboard's "quality over time" view, which wants events, not
  current-state snapshots.
- Matches the fail-open, insert-only shape of every other write path in
  `storage.py`.
- "Current" rating for a sentence, wherever a query needs it (not
  required by any query in section 3, but noted here for any future
  consumer), is `rating` from the row with **`MAX(id)`, not
  `MAX(created_at)`** — two votes in the same wall-clock second would tie
  under `MAX(created_at)` (only second resolution); `id` is monotonic by
  insertion order and never ties.

### `storage.py` addition

```python
def save_feedback(essay_id: int, sentence_index: int, rating: str) -> None:
    """Persist a thumbs-up/down vote on a sentence's flagged question-group.

    Append-only: re-voting inserts a new row rather than updating the
    existing one, so history is preserved. Failures are the caller's
    responsibility to handle (fail open — a feedback-write error must
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
```

`init_db()` (in `storage.py`) gains the `CREATE TABLE IF NOT EXISTS
feedback (...)` + index statements alongside the existing `essays`/
`questions` (and, per `00_timing_schema.md`, `llm_calls`) table creation —
same function, additive block, no changes to the existing table
statements.

## 3. Dashboard (`dashboard.py`, standalone script)

A new, separate top-level script — not a tab inside `app.py`'s
`gr.Blocks`. Own process, own `gr.Blocks`, own `demo.launch()` (on a
different port than `app.py`, e.g. default Gradio port +1, or left to
Gradio's auto-port — not prescribed here). It reads the same
`config.DB_PATH` sqlite file that `app.py`/`pipeline.py` write to, and
covers **two** sections: feedback quality (this spec) and LLM latency
(`00_timing_schema.md`, frozen sibling).

### Concurrency contract (shared DB, two live processes)

`app.py` (writer, via `storage.py`) and `dashboard.py` (reader) run as
separate processes against the same sqlite file concurrently. This spec's
dashboard must:

1. **Never create or alter schema.** `dashboard.py` must not call
   `storage.init_db()` or run any `CREATE TABLE`/`CREATE INDEX`/`ALTER`
   statement. It assumes the tables it queries (`questions`, `feedback`,
   `llm_calls`, `essays`) already exist because `app.py` has run at least
   once. If a table is missing, the query should fail visibly (caught,
   shown as an empty/error state in that section of the dashboard) rather
   than the dashboard attempting to create it — schema ownership stays
   entirely with `storage.py`/`app.py`'s write path.
2. **WAL mode.** `storage.init_db()` should additionally run `PRAGMA
   journal_mode=WAL` once (idempotent — sqlite persists this mode in the
   db file itself after the first call, but re-issuing it is harmless and
   documents the intent at the call site). WAL is what lets a long-lived
   or frequent reader (`dashboard.py`) coexist with a writer
   (`app.py`/`pipeline.py`) without either blocking the other for the
   common case (one writer, one-or-more readers) — this is the standard
   sqlite recommendation for exactly this read/write process split, and
   requires no application-level retry logic to get right.
3. **Short-lived, read-only, timeout-bounded connections.** Every
   dashboard query opens its own connection immediately before the query
   and closes it immediately after — no connection held open across
   Gradio callback invocations or cached at module scope. Open with
   `sqlite3.connect(DB_PATH, timeout=5)` (or a `file:...?mode=ro` URI with
   `uri=True` for a belt-and-suspenders read-only guarantee) so a
   momentary write-lock contention waits briefly and fails loudly instead
   of hanging the dashboard UI indefinitely. This mirrors the "connect,
   do one thing, close" pattern already used by every `storage.py`
   function (`save_essay`, `save_questions`) — `dashboard.py` should reuse
   that shape for reads, e.g. a small local helper:

   ```python
   def _query_df(sql: str, params: tuple = ()) -> pandas.DataFrame:
       with sqlite3.connect(DB_PATH, timeout=5) as conn:
           return pandas.read_sql_query(sql, conn, params=params)
   ```

   (`pandas` is not listed in `pyproject.toml`'s direct `dependencies`,
   but `gradio>=5.0` already pulls it in transitively — `gr.BarPlot`/
   `gr.LinePlot` are built on it internally, so `import pandas` works in
   this project's environment today without installing anything new. This
   spec relies on that transitive availability and does **not** propose
   adding `pandas` as a direct `pyproject.toml` entry — doing so would
   need the explicit dependency approval `CLAUDE.md` requires, and isn't
   necessary here. If a future change ever removes Gradio's own pandas
   dependency, that would need revisiting, but there's no reason to
   pre-emptively pin it now.)

### Section A — Feedback quality (this spec)

Goal: show good/bad ratio over time, using **only** `gr.BarPlot`/
`gr.LinePlot` (Gradio's built-in plot components — no new charting
dependency, per the coordinator's constraint). Both accept a
`pandas.DataFrame` plus column names for `x`/`y`/`color`.

Query (day-bucketed; matches `00_timing_schema.md`'s hour-bucket idiom,
using `substr(created_at, 1, 10)` for a day instead of an hour since
feedback volume is expected to be much lower than LLM call volume):

```sql
SELECT
    substr(created_at, 1, 10) AS day,
    rating,
    COUNT(*) AS n
FROM feedback
GROUP BY day, rating
ORDER BY day;
```

Rendered as a `gr.BarPlot(value=df, x="day", y="n", color="rating",
title="Feedback volume by day")` — stacked/grouped bars of good vs. bad
counts per day. This directly answers "is feedback quality trending up or
down" at a glance (rising bad-share = questioner is getting worse or
users are getting pickier; either way, worth a look).

A second, smaller query for a single summary ratio (rendered as a
`gr.LinePlot` of the *rate*, not raw counts, so volume swings don't
visually dominate):

```sql
SELECT
    substr(created_at, 1, 10) AS day,
    CAST(SUM(CASE WHEN rating = 'good' THEN 1 ELSE 0 END) AS REAL)
        / COUNT(*) AS good_rate
FROM feedback
GROUP BY day
ORDER BY day;
```

`gr.LinePlot(value=df, x="day", y="good_rate", title="Good-question rate over time")`.

Both queries join nothing beyond `feedback` itself — `rating` and
`created_at` are exactly the flat, query-friendly columns this schema was
designed to expose (mirroring `00_timing_schema.md`'s own design
rationale for `llm_calls`). Neither query changed from the per-question
draft of this schema — they only ever read `rating`/`created_at` — but
what they now *mean* changed: because `feedback` is keyed on
`(essay_id, sentence_index)` (one row per rating click) rather than one
row per question, `COUNT(*)` here is a clean count of rating decisions,
not inflated by how many questions happened to be in a given sentence's
group. A sentence with 6 flagged questions that gets one 👍 contributes
exactly 1 to `n`, same as a sentence with 1 flagged question that gets
one 👍 — the chart reflects "how many times did a student say yes/no,"
not "how many questions existed."

Optional (not required, cheap addition): a `gr.Number`/`gr.Label`
"overall good rate" stat tile computed from the same summary query
(`good_rate` of the most recent day, or an all-time aggregate) — a single
scalar next to the two plots for at-a-glance status without reading the
chart.

### Section B — LLM latency (`llm_calls`, frozen sibling schema)

Reuses the exact queries `00_timing_schema.md` already specifies as "the
queries Task 1's dashboard is expected to run directly against this
table, unchanged":

- Average duration by call type → `gr.BarPlot` (`x="call_type"`,
  `y="avg_duration_ms"`) from:
  ```sql
  SELECT call_type, AVG(duration_ms) AS avg_duration_ms, COUNT(*) AS n
  FROM llm_calls
  GROUP BY call_type;
  ```
- Failure/retry rate over time (hour buckets) → `gr.LinePlot` (`x="hour"`,
  multiple `y` series or one melted `metric`/`value` pair via `color=`)
  from the hour-bucketed query already given in `00_timing_schema.md`
  verbatim.

This spec does not alter those queries or that table — `dashboard.py`
simply issues them (via the same `_query_df` helper) as a second section
below/beside the feedback-quality section, in the same `gr.Blocks` layout
(e.g. two `gr.Tab`s: "Feedback Quality" and "LLM Latency", or two stacked
`gr.Row`s under section headers — either is acceptable; not prescribed
further here).

### Layout sketch

```python
# dashboard.py
import sqlite3
import gradio as gr
import pandas as pd
import config

DB_PATH = config.DB_PATH

def _query_df(sql, params=()):
    with sqlite3.connect(DB_PATH, timeout=5) as conn:
        return pd.read_sql_query(sql, conn, params=params)

def _feedback_volume_df(): ...   # Section A, query 1
def _feedback_rate_df(): ...     # Section A, query 2
def _llm_avg_duration_df(): ...  # Section B, query 1
def _llm_failure_rate_df(): ...  # Section B, query 2 (from 00_timing_schema.md)

with gr.Blocks(title="Write Like a Reader — Dashboard") as dashboard:
    refresh_btn = gr.Button("Refresh")
    with gr.Tab("Feedback Quality"):
        volume_plot = gr.BarPlot(x="day", y="n", color="rating")
        rate_plot = gr.LinePlot(x="day", y="good_rate")
    with gr.Tab("LLM Latency"):
        duration_plot = gr.BarPlot(x="call_type", y="avg_duration_ms")
        failure_plot = gr.LinePlot(x="hour", y="failed")  # etc.

    def _refresh_all():
        return (
            _feedback_volume_df(), _feedback_rate_df(),
            _llm_avg_duration_df(), _llm_failure_rate_df(),
        )

    dashboard.load(_refresh_all, outputs=[volume_plot, rate_plot, duration_plot, failure_plot])
    refresh_btn.click(_refresh_all, outputs=[volume_plot, rate_plot, duration_plot, failure_plot])

if __name__ == "__main__":
    dashboard.launch()
```

`dashboard.load(...)` populates plots on page open; the manual `Refresh`
button re-runs the same queries on demand (dashboard is a separate
process from `app.py`, so it won't otherwise see new feedback/calls
without a page reload or explicit refresh — no polling/websocket push is
proposed here, out of scope for this phase).

## 4. Ownership notes (shared-file convention)

Per the project's shared-file convention (each spec declares which hunks
of a shared file it owns vs. depends on, so parallel phases don't step on
each other):

### `models.py`
- **This spec does not depend on, read, or touch `Question.id`,
  `QuestionRecord.id`, or `PipelineResult.all_questions`** — those were
  `00_question_id.md`'s additions and that spec is now SUPERSEDED. Feedback
  keys on `(essay_id, sentence_index)` instead, so none of that machinery
  is needed. Agent 2 is separately reverting the corresponding
  `all_questions` addition that had been made to `02_speed.md` to support
  the now-abandoned per-question id.
- **One small, new addition:** `PipelineResult.essay_id: int | None = None`
  (see "Getting `essay_id` onto `PipelineResult`" in section 1) — this is
  the only field this spec adds to `models.py`. It is unrelated to, and
  does not resurrect, anything from `00_question_id.md`.
- No changes to `Question`, `QuestionRecord`, or `Annotation`.

### `storage.py`
- **Owned by `00_timing_schema.md`:** the `llm_calls` table + `CREATE
  INDEX` statements inside `init_db()`, and `save_llm_call(...)`.
- **No dependency on `00_question_id.md`'s `save_questions` return-type
  change** — this spec no longer needs `save_questions` to return
  anything, since feedback doesn't key on a per-question db id. If that
  spec's `save_questions` change is rolled back as part of the
  supersession, this spec is unaffected either way.
- **New in this spec, additive, no conflict with the above:**
  - `feedback` table (`id`, `essay_id`, `sentence_index`, `rating`,
    `created_at`) + its two `CREATE INDEX` statements, added inside
    `init_db()` as their own block (alongside, not replacing, the
    `essays`/`questions`/`llm_calls` blocks).
  - `save_feedback(essay_id: int, sentence_index: int, rating: str) -> None`
    — new function, does not modify `save_essay`, `save_questions`, or
    `save_llm_call`.
  - The `PRAGMA journal_mode=WAL` addition to `init_db()` (section 3,
    concurrency contract) — this is the one place this spec touches
    something not purely additive to a *table*, but it's still additive
    to `init_db()`'s body (one more `conn.execute(...)` line) and does
    not change any existing statement. Flagged explicitly here since it
    affects every table's readers/writers, not just `feedback` — if
    `00_timing_schema.md`'s implementation phase also wants WAL mode for
    its own dashboard section, this spec's PRAGMA addition already covers
    it; it should not be added twice.

### `pipeline.py`
- **Owned by `02_speed.md`:** the `essay_id: int | None = None` parameter
  added to `run()`'s signature (for `llm_calls` timing-row attribution).
- **New in this spec:** passing that same `essay_id` parameter through to
  the `PipelineResult(...)` constructor call inside `run()` — a one-line
  addition (`PipelineResult(..., essay_id=essay_id)`) at the point where
  `run()` builds its return value — per "Getting `essay_id` onto
  `PipelineResult`" in section 1. This is deliberately *not* a post-hoc
  `result.essay_id = essay_id` mutation from `app.py` after `run()`
  returns; `essay_id` is set at construction, inside `pipeline.py`, using
  the parameter `02_speed.md` already threads in. Small, additive, does
  not touch `_parse_questions`, `_check_answers`, or the
  question-generation loop itself.

### `app.py`
- **New in this spec:** one `good_btn`/`bad_btn` pair and a
  `feedback_status_md` added below the existing `detail_panel`, a
  `current_selection_state` (`gr.State`), the corresponding small change
  to `on_select`'s return signature (now returns `(markdown, selection)`
  instead of just `markdown`), and the two click handlers. This is a much
  smaller footprint on `app.py` than the earlier per-question row-pool
  design — `on_select`'s rendering of `detail_panel` itself is unchanged
  from today's code. No other spec currently touches `app.py`'s
  `on_select` or the `gr.Blocks` layout, so this is a clean addition — but
  any later "output format" work (Task 3) that also touches how
  `annotation.questions` gets rendered in `app.py` should be aware
  `on_select`'s signature now includes a second return value.

### `dashboard.py`
- **New file, wholly owned by this spec.** `00_timing_schema.md` defines
  the `llm_calls` table and its intended dashboard queries but does not
  itself create `dashboard.py` — this spec is what actually stands the
  script up, for both sections.

## Explicitly out of scope for this phase

- Re-vote/undo UI beyond "click again overwrites the visible status
  message" (history is preserved in the table regardless).
- Auth/access control on `dashboard.py` (assumed internal/investor-facing,
  same trust level as the rest of this demo per `CLAUDE.md`).
- Live-updating the dashboard without a manual refresh or page reload.
- Any change to `00_timing_schema.md`'s table, hook points, or queries.

## Reviewer sign-off

Reviewed by Agent 1R. Five findings, all addressed in this revision:

1. **Bug — `partial`/keyword collision in the click handler.** The
   original `partial(_rate, i, rating=...)` wiring raised `TypeError: got
   multiple values for argument 'rating'`, since Gradio fills the next
   open positional slot with its `inputs=` value, colliding with the
   keyword-bound `rating`. Fixed in "Click handler" by reordering
   `_rate`'s signature to `(row_index, questions_state, rating)` (so
   `partial`'s positional binding no longer collides) and additionally
   documenting a per-row-closure alternative that sidesteps the
   positional/keyword ordering question entirely.
2. **Gap — missing `outputs=[...]` list.** "Component design" now spells
   out the full `highlighted.select(...)` wiring: 40 per-row component
   outputs (5 components × `MAX_QUESTIONS_PER_ANNOTATION` rows) plus
   `overflow_md` plus `current_questions_state`, and states explicitly
   that `current_questions_state` must be an `on_select` *output* (not
   just a click-handler input) — otherwise click handlers would vote
   against a stale selection.
3. **Silent truncation.** Verified the questioner's actual bound against
   `prompts.build_questioner_prompt` ("3 to 4" questions per sentence) and
   noted explicitly that this is prompt-suggested, not code-enforced
   (`pipeline._parse_questions` caps nothing). `on_select`/`_row_updates`
   now truncate to `MAX_QUESTIONS_PER_ANNOTATION` explicitly and show a
   visible `overflow_md` "+N more" indicator whenever an annotation
   exceeds the cap, instead of dropping the extras with no trace.
4. **Tie-break ambiguity.** "One row per vote" now commits to `MAX(id)`
   (monotonic, never ties) instead of leaving `MAX(created_at)` vs.
   `MAX(id)` an open choice — `created_at` has only second resolution and
   two votes in the same second would tie under it.
5. **Dependency conflict.** The concurrency-contract section no longer
   frames `pandas` as a possible new direct dependency needing approval.
   It now states plainly that `gradio>=5.0` already pulls in `pandas`
   transitively (`gr.BarPlot`/`gr.LinePlot` are built on it), so
   `dashboard.py` can `import pandas` without any `pyproject.toml`
   change or separate approval ask.

## Redesign: sentence-grain feedback (post-review, user-directed)

After the above review pass, the user identified a real UX problem with
the per-question design this spec originally had: a 10-sentence draft at
3–4 questions/sentence could require up to ~40 individual thumbs-up/down
clicks to rate every flagged question. The correct grain is one rating
per sentence's question-group ("are the questions for this sentence good
or bad?"), not one per question. Two follow-on decisions came with that:

1. **Feedback now keys on `(essay_id, sentence_index)`, one row per
   rating action** — not one row per question. This gives clean dashboard
   counts (one click = one row) that aren't skewed by how many questions
   a given sentence happened to generate.
2. **`Question.id` is dropped entirely.** Nothing needs it once feedback
   doesn't key on individual questions. `docs/specs/00_question_id.md` is
   now marked SUPERSEDED (handled outside this spec). Agent 2 is
   separately reverting the `all_questions` addition in `02_speed.md`
   that existed only to support the now-abandoned per-question id.

This revision rewrites the doc accordingly:

- **§1** replaces the fixed pool of per-question rows with today's
  original single `gr.Markdown` rendering plus one thumbs-up/down button
  pair per selection, keyed on a new `current_selection_state`
  (`(essay_id, sentence_index)`) rather than `Question.id`.
  `MAX_QUESTIONS_PER_ANNOTATION` and the overflow indicator are gone —
  irrelevant once there's no per-question row cap. This also removes the
  `partial`/keyword-collision hazard from finding #1 above entirely
  (the click handlers are now trivial single-argument lambdas), so that
  finding is moot under the new design rather than needing a separate
  fix.
- **§2** changes `feedback` to `(id, essay_id, sentence_index, rating,
  created_at)`, FK'd to `essays(id)` instead of `questions(id)`.
  `storage.save_feedback` becomes
  `save_feedback(essay_id: int, sentence_index: int, rating: str) -> None`.
- **§3** dashboard queries are structurally unchanged (still group by
  day/rating off `feedback`) — only the note about what `COUNT(*)` means
  changed, now stated explicitly: counts are clean rating-decision counts,
  no longer subject to per-question skew.
- **§4** ownership no longer lists any dependency on `00_question_id.md`
  or `Question.id`; this spec now touches `models.py` only via one new
  `PipelineResult.essay_id` field, unrelated to the superseded id work.

## Delta fix: `essay_id` threading is not an open choice

Agent 1R's delta review on the sentence-grain redesign flagged that §1
presented "post-hoc `result.essay_id = essay_id` mutation" vs. "threading
into `run()`" as an either-way choice. It isn't: `essay_id` is already
known before `pipeline.run(...)` is even called (`app.py`'s
`storage.save_essay(draft_text)` call precedes it), so there's no
after-construction moment to mutate into, unlike the old per-question id
which genuinely couldn't be known until after `storage.save_questions`
returned. "Getting `essay_id` onto `PipelineResult`" now commits to
threading it into `run()` at construction time, and explicitly says to
reuse the `essay_id: int | None = None` parameter `02_speed.md` already
added to `run()`'s signature (for its own `llm_calls` attribution) rather
than introducing a second/separate mechanism — same field, same call-site
change (`pipeline.run(draft_text, essay_id=essay_id, on_progress=on_progress)`),
not duplicated.
