# Timing Instrumentation Schema (Phase A)

Status: **FROZEN CONTRACT**, extended additively (see "Revision: batching +
token tracking" below). This schema is shared with Task 1 (feedback-capture
spec), which will build a dashboard latency chart directly against the table
defined here. Column names/types are not up for renegotiation once this lands —
if a later phase needs more, add a new table or nullable column, don't rename
or restructure this one. The revision below follows exactly that rule: every
change is a new nullable column or a loosened constraint, nothing existing is
renamed or removed.

## Why this table

`pipeline.run()` loops over sentences and makes up to two blocking LLM calls
per sentence (questioner, checker), each going through
`llm_client.generate_json()`, which itself may retry silently (transient
backend errors, or a JSON-parse retry) before succeeding or raising
`LLMError`. The reported ~20s latency is dominated by this serial call
pattern, not by `spaCy` sentence splitting. Before parallelizing (Phase B),
we need per-call timing data to see: how many calls per essay, how long each
takes, how often retries/failures happen, and whether questioner vs. checker
calls cost differently. This table is that instrumentation.

**Revision note (Phase B, additive):** Task 2's speed design changed from
per-sentence parallelization to **batching** — one questioner call and one
checker call per submission, covering up to `MAX_SENTENCES = 20` sentences,
instead of one call per sentence. A single `llm_calls` row can now describe a
call that spans many sentences, not just one. `sentence_index` alone can no
longer identify "which sentence(s) this call was about" for a batched call —
see the schema changes below.

## Schema

Follows the conventions already in `storage.py` (`essays`, `questions`):
`INTEGER PRIMARY KEY AUTOINCREMENT`, `FOREIGN KEY` reference via `REFERENCES`,
ISO 8601 UTC string timestamps (`datetime.now(timezone.utc).isoformat()`,
matching `save_essay`).

```sql
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
);

CREATE INDEX IF NOT EXISTS idx_llm_calls_essay_id ON llm_calls(essay_id);
CREATE INDEX IF NOT EXISTS idx_llm_calls_call_type ON llm_calls(call_type);
CREATE INDEX IF NOT EXISTS idx_llm_calls_created_at ON llm_calls(created_at);
```

Two changes to existing columns, both loosening rather than
renaming/removing, plus three new nullable/defaulted columns:

- **`sentence_index` is now nullable** (was `NOT NULL`). A per-sentence
  call (the original design, still valid for any future non-batched call
  site) sets it as before; a batched call that covers a range of
  sentences leaves it `NULL` — there's no single sentence index that
  describes "sentences 0 through 19." `sentence_count` (below) is what a
  batched row uses instead.
- **`sentence_count` is new**, `INTEGER NOT NULL DEFAULT 1`. How many
  sentences a given call covered: `1` for the original per-sentence
  granularity (the `DEFAULT 1` makes old rows and old call sites
  correct without any migration), up to `MAX_SENTENCES = 20` for a
  batched call under the new design. This is what makes `duration_ms /
  sentence_count` (a per-sentence cost estimate) meaningful for both old
  and new rows.
- **`prompt_tokens` / `completion_tokens` are new**, both nullable.
  Token usage for the call, when the backend reports it — see "Hook
  points" below.

### Column notes

- **`id`** — call id, per row (one row per `generate_json()` invocation from
  `pipeline.py`, i.e. one row per questioner or checker "round", not one row
  per underlying HTTP request — see "Granularity" below).
- **`essay_id`** — FK to `essays(id)`, same pattern as `questions.essay_id`.
- **`sentence_index`** — for a per-sentence call, matches the `i` loop
  index in `pipeline.run()` (0-based, same indexing as
  `Annotation.sentence_index` / `QuestionRecord`). **`NULL` for a batched
  call** (Task 2's current design — one questioner + one checker call per
  submission, covering `sentence_count` sentences, not one) since no
  single index identifies the sentences involved. Queries that want
  "which essay/how many sentences" for a batched row use `essay_id` +
  `sentence_count` instead.
- **`sentence_count`** — how many sentences this call covered. `1` for a
  per-sentence call (the default, and what every pre-batching row has);
  up to `MAX_SENTENCES = 20` for a batched call under Task 2's revised
  design. Always populated (`NOT NULL`), unlike `sentence_index`, so
  `duration_ms / sentence_count` is always a valid per-sentence-cost
  computation regardless of which granularity produced the row.
- **`call_type`** — `'questioner'` for the call in `pipeline.run()`,
  `'checker'` for the call in `pipeline._check_answers()`. Enforced via
  `CHECK` (sqlite has no native enum type; this is the idiomatic substitute
  and matches how this project should express fixed value sets).
- **`status`** — `'success'` if `generate_json()` returned parsed data,
  `'failed'` if it raised `llm_client.LLMError` (the pipeline's fail-open
  path: `result.failed_rounds.append(i)` in `run()`, or `return questions`
  unchanged in `_check_answers()`). A failed call is never dropped —
  it still gets a row, with `error_message` populated.
- **`retries`** — count of retry attempts consumed inside `generate_json()`
  for this logical call: transient backoff retries (the
  `max_transient_retries` loop around `_call_model`) plus the one JSON-parse
  retry (the `retry_prompt` branch), summed. `0` means the call succeeded
  clean on the first attempt. This is what makes retried calls
  distinguishable from clean ones without needing a second table — dashboard
  can do `WHERE retries > 0` or `AVG(retries)` directly.
- **`duration_ms`** — wall-clock time for the *entire* `generate_json()` call,
  including any internal retry/backoff sleep. This is deliberate: it's the
  number that actually explains latency to a dashboard viewer. If Phase B
  needs backoff-sleep-excluded timing later, that's an additive column, not
  a change to this one.
- **`prompt_tokens`** — input/"reading" token count for the call, from
  Ollama's chat response `prompt_eval_count` field. Nullable: a future
  non-Ollama backend that doesn't report token usage simply leaves this
  `NULL` rather than needing a schema change or a sentinel value.
- **`completion_tokens`** — output/"writing" token count for the call,
  from Ollama's chat response `eval_count` field. Same nullability
  rationale as `prompt_tokens`. Both are `NULL` together in practice
  (either the backend reports usage or it doesn't), but they're
  independently nullable rather than coupled by a constraint, since
  there's no correctness reason to forbid a backend that reports one but
  not the other.
- **`error_message`** — `str(exc)` from the caught `LLMError`, `NULL` on
  success.
- **`created_at`** — ISO 8601 UTC timestamp of when the call started (set
  from the same clock convention as `essays.created_at`). Used for
  time-bucketing in the dashboard (`substr(created_at, 1, 13)` for
  hour-buckets, etc.).

### Granularity: one row per pipeline call site, not per HTTP request

`generate_json()` can make up to 3 underlying `_call_model()` HTTP calls for
a single logical questioner/checker round (2 transient retries + 1
JSON-retry). This spec records **one row per logical round** (i.e., one row
per call to `generate_json()` from `pipeline.py`), with `retries` capturing
how many extra attempts happened inside it. This keeps the table directly
joinable/groupable against `sentence_index` and `call_type` at the
granularity the dashboard cares about ("how long did the checker call for
sentence 4 take, end to end") without needing a sub-attempt table. If
per-attempt-level detail is ever needed, that's a separate child table
(`llm_call_attempts`, FK to `llm_calls.id`) — out of scope here and not
required by the frozen contract.

## Hook points

Two call sites in `pipeline.py`, both currently call
`llm_client.generate_json(...)` directly:

1. **`pipeline.run()`** — the questioner call:
   ```python
   data = llm_client.generate_json(prompt, retry_prompt=prompts.QUESTIONER_RETRY)
   ```
2. **`pipeline._check_answers()`** — the checker call:
   ```python
   data = llm_client.generate_json(prompt, retry_prompt=prompts.CHECKER_RETRY)
   ```

Both are already wrapped in `try/except llm_client.LLMError`, which is
exactly where `status` and `error_message` fall out naturally. The cleanest
hook is to wrap each call site with `time.perf_counter()` before/after and
persist a row in the `except`/success paths — no change to `llm_client.py`'s
public behavior required for `duration_ms` or `status`.

**Token usage capture.** Ollama's chat response already includes
`prompt_eval_count` (input/"reading" tokens) and `eval_count`
(output/"writing" tokens) natively — `llm_client.generate_json()` today
extracts just the parsed JSON content from that response and discards the
rest. To populate `prompt_tokens`/`completion_tokens`, the response's
`prompt_eval_count`/`eval_count` need to be captured alongside
`duration_ms`/`status` at the same two call sites (`pipeline.run()`'s
questioner call, `pipeline._check_answers()`'s checker call), rather than
being dropped after the content string is pulled out. This is the same
shape of change as the `retries` hook below — `llm_client.py`'s response
handling needs to expose one or two more fields from a response it
already has in hand, not make a new call or change its retry/success
semantics. If a future non-Ollama backend's response doesn't include
these fields, the call site simply persists `NULL` for both — no special
casing required, since both columns are nullable for exactly this
reason.

The one piece `pipeline.py` cannot currently see is **`retries`** —
`generate_json()` retries internally and doesn't expose the count on
success. Recommended minimal change (for the implementation phase, not this
spec): give `llm_client.generate_json()` an optional callback parameter,
e.g. `on_attempt: Callable[[], None] | None = None`, invoked once per retry
attempt (transient backoff retry or JSON-retry) inside its existing loops
(around the `attempt < max_transient_retries` branch in the transient loop,
and around the `retry_prompt` branch). The call site in `pipeline.py` passes
a closure that increments a local counter, then persists
`retries=<counter>` alongside `duration_ms`/`status` once the call resolves.
This keeps `llm_client.py`'s retry logic itself untouched — only a counting
hook is added — and keeps timing/persistence logic entirely in
`pipeline.py`, where `essay_id`, `sentence_index`, and `call_type` are
already in scope.

Persistence should follow the existing `storage.py` convention (see
`save_essay` / `save_questions`): a new `storage.save_llm_call(essay_id,
sentence_index, sentence_count, call_type, status, retries, duration_ms,
prompt_tokens=None, completion_tokens=None, error_message=None)` function
— `sentence_count` added for the batching revision, `sentence_index` now
accepting `None`, `prompt_tokens`/`completion_tokens` added as optional
keyword params defaulting to `None` for backends that don't report them —
called from `pipeline.py` at each of the two hook points, that
does its own `init_db()` + `sqlite3.connect(DB_PATH)` + `INSERT`. Like the
existing save functions, failures here should fail open — a timing-write
error must never block a student from getting their feedback.

## Dashboard-query shape this schema is designed for

These are the queries Task 1's dashboard is expected to run directly against
this table. The original three keep working unchanged against the revised
schema — none of their columns were renamed, and none of them reference
`sentence_index` in a way that a `NULL` (batched-row) value breaks:

```sql
-- Average duration by call type
SELECT call_type, AVG(duration_ms), COUNT(*)
FROM llm_calls
GROUP BY call_type;

-- Failure/retry rate over time (hour buckets)
SELECT substr(created_at, 1, 13) AS hour,
       COUNT(*) FILTER (WHERE status = 'failed') AS failed,
       COUNT(*) FILTER (WHERE retries > 0) AS retried,
       COUNT(*) AS total
FROM llm_calls
GROUP BY hour
ORDER BY hour;

-- Slowest sentences for one essay
SELECT sentence_index, call_type, duration_ms
FROM llm_calls
WHERE essay_id = ?
ORDER BY duration_ms DESC;
```

(The third query's `sentence_index` column will simply read `NULL` for any
batched row under Task 2's revised design — still valid SQL, still orders
correctly by `duration_ms`, just less specific per-row than it was when
every call was single-sentence. A dashboard wanting to label batched rows
distinctly can do so with a `CASE WHEN sentence_index IS NULL THEN
'batch (' || sentence_count || ' sentences)' ELSE sentence_index END`
expression, but that's a display nicety, not required for the query to
keep working.)

Two new queries, added by this revision, for the columns it introduces:

```sql
-- Per-sentence cost (duration normalized by how many sentences the call covered)
SELECT call_type, AVG(duration_ms * 1.0 / sentence_count) AS avg_ms_per_sentence
FROM llm_calls
GROUP BY call_type;

-- Average token usage by call type
SELECT call_type,
       AVG(prompt_tokens) AS avg_prompt_tokens,
       AVG(completion_tokens) AS avg_completion_tokens,
       AVG(prompt_tokens + completion_tokens) AS avg_total_tokens
FROM llm_calls
WHERE prompt_tokens IS NOT NULL AND completion_tokens IS NOT NULL
GROUP BY call_type;
```

The token query's `WHERE ... IS NOT NULL` guard is what makes it safe
against rows from a backend that didn't report usage (or any pre-revision
row, which will have `NULL` in both columns) — those rows are excluded
from the average rather than silently zeroing it out via SQLite's
NULL-skipping `AVG()` behavior mixed with rows that have partial data.

`call_type`, `status`, `retries`, `duration_ms`, `sentence_count`,
`prompt_tokens`, `completion_tokens`, and `created_at` are all flat,
indexed or index-friendly columns specifically so these queries need no
joins beyond the existing `essay_id` FK and no post-processing.

### Composes cleanly with `01_feedback_capture.md`'s dashboard

`01_feedback_capture.md`'s "Section B — LLM latency" reuses this file's
queries verbatim and adds nothing of its own beyond issuing them through
its `_query_df` helper. Since every change here is additive (new nullable
columns, one loosened `NOT NULL` → nullable on `sentence_index`, one new
`DEFAULT`-backed column), none of that spec's existing wiring breaks:
its two existing plots (`gr.BarPlot` on average duration by call type,
`gr.LinePlot` on hourly failure/retry rate) read columns
(`call_type`, `duration_ms`, `created_at`, `status`, `retries`) that are
untouched by this revision. The two new queries above are optional
additions for that dashboard — a "per-sentence cost" bar and a "token
usage by call type" bar/table — not required changes to what's already
specified there.
