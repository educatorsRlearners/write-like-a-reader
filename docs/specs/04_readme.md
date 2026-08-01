# Spec: README Rewrite

**Status:** Spec only — this document is a proposed replacement for the
repo's top-level `README.md`, not an edit to that file yet. It has no code
diffs; the "deliverable" is the block of README-toned Markdown in the
"Proposed `README.md`" section below, ready to paste in wholesale once
implementation of the other four specs begins.

## Why this rewrite

The current `README.md` is close but has drifted in a few places once
checked against the actual code:
- It frames the app as "Questioner"/"Answer-checker" *agents* and describes
  highlighting as inline-on-first-pass; the real `pipeline.run()` loop and
  `highlight.py` do match this in spirit, but the README has no mention of
  the sqlite persistence (`storage.py`) that already runs on every
  submission (`save_essay`/`save_questions`), which is worth surfacing since
  it's live, user-visible-in-spirit (there's a data-retention notice in the
  app UI itself) behavior today, not a future feature.
- It has no pointer to `docs/specs/`, which didn't exist when it was last
  written.
- Specs including `00_timing_schema.md` (frozen), `01_feedback_capture.md`,
  `02_speed.md`, and `03_output_format.md` are signed off
  (`05_integration_notes.md`) and describe real, upcoming changes —
  including a new dependency (`pysbd`) — that a reader of the README should
  know are coming without mistaking them for already-shipped. (An earlier
  `00_question_id.md` spec, threading a stable id onto `Question`, has since
  been superseded/retired by `01_feedback_capture.md`'s redesign to
  per-sentence feedback, which no longer needs a per-question id — it's not
  referenced below.)

This spec's job is narrow: describe today's app accurately, then summarize
what's proposed next, clearly separated.

## Verification notes (current-state claims below, checked against code)

- `app.py`: single `gr.Blocks` app, launched via `demo.launch()` under
  `if __name__ == "__main__"`. Run today with `uv run app.py`.
- `pipeline.run()`: serial `for i, sentence in enumerate(sentences)` loop,
  one questioner call and (except on the last sentence) one checker call
  per sentence, both through `llm_client.generate_json()` against a local
  Ollama model. No batching, no timing instrumentation yet — that's
  `02_speed.md`/`00_timing_schema.md`. (`02_speed.md` originally proposed
  parallelizing these per-sentence calls with a thread pool; that design
  was replaced after an empirical test found Ollama serializes requests
  server-side on this hardware, so there was no concurrency to gain — see
  the "Planned / in progress" section below for the current design.)
- `sentence_split.py`: still spaCy (`en_core_web_sm`) today. `pysbd` is not
  in `pyproject.toml`'s `dependencies` (confirmed) — only
  `gradio`/`ollama`/`python-dotenv`/`spacy`. The swap is `02_speed.md`,
  unimplemented.
- `storage.py`: `init_db()` creates two tables today, `essays` and
  `questions`, in a local sqlite file at `config.DB_PATH` (default
  `data/essays.db`, overridable via `DB_PATH` env var). `save_essay`/
  `save_questions` are called from `app.get_feedback`, fail-open (a storage
  error is logged and swallowed, never blocks the student's feedback). No
  `feedback` or `llm_calls` tables yet, no `dashboard.py` file yet — both
  proposed in `01_feedback_capture.md`/`00_timing_schema.md`.
- `models.py`: `Question` is currently just `text: str` — no length/prefix
  normalization on question text. Proposed in `03_output_format.md`.
- `app.py`'s question detail panel is one `gr.Markdown` per selection today
  (`on_select` returns a joined `"- {q.text}"` bullet list) — no
  thumbs-up/down controls. Proposed in `01_feedback_capture.md`, which now
  rates a sentence's whole flagged-question group at once (keyed on
  `essay_id`/`sentence_index`), not each question individually.
- Tests exist today (`tests/`) for pipeline, storage, highlight,
  sentence_split, and llm_client — `uv run pytest` is accurate as-is.

## Proposed `README.md`

The block below is the literal proposed replacement content.

---

```markdown
# Write Like a Reader

A demo app that gives composition students feedback on their expository
writing. A student pastes or uploads a paragraph or two; an LLM agent (the
"Questioner") asks the Wh-questions a reader would have after each sentence,
and a second LLM agent (the "Answer-checker") checks whether the very next
sentence answers them. Unanswered questions are highlighted inline on the
draft, so the student can revise their own draft — the tool flags gaps, it
doesn't fix them.

This is a demo / proof-of-concept, used internally and with investors. It's
built for English 101/102 students uploading their own drafts; instructors
recommend it but aren't direct users of the app itself.

See `CLAUDE.MD` for the full project brief and `docs/write_like_a_reader.md`
for the classroom activity this automates.

## How it works today

1. You paste or upload (`.txt`) a draft into the Gradio UI (`app.py`).
2. `sentence_split.py` (spaCy) splits it into sentences.
3. `pipeline.py` walks the sentences one at a time. For each one, it asks a
   local LLM (via [Ollama](https://ollama.com)) what a reader would still
   want to know at that point, then asks a second LLM call whether the
   *next* sentence answers those questions.
4. Answered questions are dropped silently. Unanswered ones are attached to
   that sentence as an annotation.
5. `highlight.py` turns the annotations into Gradio `HighlightedText` spans;
   clicking a highlighted sentence shows its unanswered questions.
6. Every submitted draft and its generated questions are saved to a local
   SQLite database (`data/essays.db` by default) — the app's UI shows a
   data-retention notice to this effect. Storage failures never block the
   student from getting feedback (fail open).

There's no accounts, no auth, and no cloud LLM calls — everything runs
against a local Ollama model.

## Setup

Requires Python >=3.12 (see `pyproject.toml`).

1. Install dependencies and the spaCy model:

   ```
   uv sync
   uv run python -m spacy download en_core_web_sm
   ```

2. Install [Ollama](https://ollama.com) and pull the model the app uses:

   ```
   brew install ollama
   ollama pull qwen2.5:3b
   ```

   Make sure the Ollama service is running (`ollama serve`, or just launch
   the Ollama app — it runs in the background) before starting the app
   below. The app calls the local Ollama API (`http://localhost:11434` by
   default), so no network access or API token is required at runtime
   (the one-time spaCy model download in step 1 above does need network
   access).

   Optional env vars (set in a `.env` file if you want to override the
   defaults): `OLLAMA_MODEL` (default `qwen2.5:3b`), `OLLAMA_HOST` (default
   is Ollama's own local default), `OLLAMA_TIMEOUT` (seconds, default `60`),
   `DB_PATH` (default `data/essays.db`).

3. Run the tests:

   ```
   uv run pytest
   ```

4. Launch the app:

   ```
   uv run app.py
   ```

## Input limits

There's a soft cap of ~3000 words per draft (`config.MAX_WORDS`) — longer
drafts still run, but the UI warns that they may take a while and can hit
rate limits. This is a soft/demo-stage limit, not a hard architectural
ceiling.

## Verifying the local model end-to-end

Before treating this as demo-ready, run one full pass with Ollama actually
serving the model:
- Confirm `ollama serve` is running and `ollama pull qwen2.5:3b` has
  finished.
- Paste in a short (1-2 paragraph) sample essay and confirm the Questioner
  asks sensible questions and the Answer-checker's answered/unanswered calls
  look right.
- Stop Ollama and confirm the app fails gracefully (matching the existing
  backend-unreachable handling in `pipeline.py`) rather than crashing.

## Planned / in progress

The following are **design specs, not shipped features** — see
`docs/specs/` for full detail. They're listed here so anyone skimming the
README knows what's coming without mistaking a spec for working code.

- **Feedback capture + dashboard** (`docs/specs/01_feedback_capture.md`) —
  adds a thumbs-up/down control per sentence, to rate whether the questions
  flagged for that sentence were good or bad, as a group (not each flagged
  question individually), a new `feedback` table in SQLite, and a
  standalone `dashboard.py` (a second Gradio app) for reviewing feedback
  trends and LLM call latency.
- **Speed: single-batch calls + pysbd** (`docs/specs/02_speed.md`) — an
  earlier version of this spec proposed running per-sentence LLM calls
  concurrently via a thread pool; an empirical test found Ollama serializes
  requests server-side on this hardware, so that approach was replaced with
  single-batch calls instead — one questioner call and one checker call
  cover the *whole* submission at once, rather than a call pair per
  sentence — plus explicit `num_ctx` tuning for the model's context window.
  This is paired with two new, tighter soft caps that make single-batch
  feasible without chunking: `config.MAX_WORDS` drops from ~3000 to ~1000,
  and a new `config.MAX_SENTENCES = 20` cap is added. Also replaces the
  `spaCy` sentence splitter with the lighter-weight `pysbd` library, and
  adds per-call timing instrumentation to SQLite — now tracking token usage
  (prompt/completion token counts) alongside call duration. **`pysbd` is a
  pre-approved but not-yet-added dependency** — it is not in
  `pyproject.toml` today. LangChain (and similar LLM-orchestration
  frameworks) was explicitly considered and rejected for this work: it
  doesn't address either verified bottleneck — Ollama's server-side request
  serialization, or the context-window limit the new caps exist to respect
  — so adopting it would add a dependency without fixing anything.
- **Question output format** (`docs/specs/03_output_format.md`) — caps
  generated questions at three sentences and prefixes each with its
  Wh-word category (e.g. `Who:`, `How long:`) so students can scan flagged
  questions faster.
- **This README** (`docs/specs/04_readme.md`) — the spec this file was
  generated from.

Two small implementation notes carried forward from spec review
(`docs/specs/05_integration_notes.md`), for whoever implements the above:
`storage.init_db()` will need the additive table/index blocks from the
timing and feedback specs concatenated by hand; and if `_check_answers`
gets folded into the single-batch call flow, the checker-prompt
prefix-stripping step from the output-format spec needs to be carried over
manually.

(Note: `05_integration_notes.md` itself predates `02_speed.md`'s rework
from per-sentence parallelization to single-batch calls — its wording still
describes the older per-sentence-worker design. The carry-forward note
above has been updated here to match the current design; the underlying
integration doc is unchanged.)

## Project specs

Full design detail for both shipped and in-progress work lives in
[`docs/specs/`](docs/specs/) — start with `05_integration_notes.md` for the
current sign-off state of the in-progress specs above.
```

---

## Ownership notes

This spec owns only `docs/specs/04_readme.md` (this file) and the eventual
content of `README.md` once an implementation phase copies the block above
into place. It does not modify any other file, and depends on nothing from
the other four specs beyond describing them accurately at summary level —
no shared code, no `models.py`/`storage.py`/`pipeline.py` hunks.

## Explicitly out of scope

- Actually overwriting `README.md` (implementation-phase action, not this
  spec).
- Screenshots/GIFs of the running app.
- A changelog or version history section.
- Documenting `CLAUDE.MD`'s "Hard Stops"/"Known Gotchas" sections in the
  README itself — those stay owned by `CLAUDE.MD` as internal-contributor
  guidance; the README stays user/setup-facing.

## Reviewer sign-off

Reviewed by Agent 4R. All current-state claims verified against the actual
code; accuracy, setup instructions, and `CLAUDE.md` consistency all check
out. No blocking issues. Three polish items addressed in this revision:

1. **Editorializing on storage motive.** "How it works today" step 6
   claimed drafts/questions are saved "so we can review and improve the
   tool over time." Trimmed to describe only the behavior (saved to local
   SQLite + the UI's data-retention notice), no motive claim.
2. **Missing Python version requirement.** Setup had no mention of the
   `>=3.12` requirement in `pyproject.toml`, which could produce an opaque
   `uv sync` failure for a contributor on an older Python. Added a one-line
   callout at the top of the Setup section.
3. **"No network access... required" read as contradicting the spaCy
   model download.** Scoped the claim explicitly to runtime ("no network
   access or API token is required at runtime") and added a parenthetical
   noting the one-time `en_core_web_sm` download in step 1 does need
   network access.

**Post-review update:** `docs/specs/01_feedback_capture.md` was redesigned
after this spec was finalized — feedback is now rated per-sentence (one
thumbs-up/down for a sentence's whole flagged-question group, keyed on
`essay_id`/`sentence_index`), not per-individual-question, and
`docs/specs/00_question_id.md`'s stable `Question.id` is superseded/retired
as a result (nothing in the current design needs it). Updated this file
accordingly: the feedback-capture bullet under "Planned / in progress" now
describes per-sentence, group-level rating instead of per-question rating;
the `models.py` verification note no longer credits a proposed `id` field
to `00_question_id.md`; the "Why this rewrite" intro now flags
`00_question_id.md` as superseded/retired rather than listing it alongside
the other signed-off specs; and the `init_db()` carry-forward note no
longer references a question-id DDL block. No other stale per-question-id
references were found on spot-check.

**Post-review update 2:** `docs/specs/02_speed.md` was reworked after this
spec was finalized — an empirical test found Ollama serializes requests on
this hardware, so the `ThreadPoolExecutor` per-sentence parallelization
design this file previously described no longer works and has been
replaced with single-batch calls (one questioner call + one checker call
covering the whole submission at once) plus explicit `num_ctx` tuning.
Single-batch is feasible because of two new, tighter soft caps introduced
in the same rework: `config.MAX_WORDS` drops from ~3000 to ~1000, and a new
`config.MAX_SENTENCES = 20` cap is added. The `llm_calls` timing table also
now captures token usage (prompt/completion token counts), not just call
duration. Updated this file accordingly: the speed bullet under "Planned /
in progress" now describes single-batch calls and the new caps instead of
thread-pool parallelization, and explicitly notes that LangChain (and
similar orchestration frameworks) was considered and rejected — it
addresses neither verified bottleneck (Ollama's server-side request
serialization, or the context-window limit motivating the new caps), so it
would add a dependency without fixing anything; the corresponding
verification note and the `05_integration_notes.md` carry-forward note were
also updated to stop describing a "parallelized per-sentence worker." The
current-state "Input limits" section (describing today's actual, unchanged
~3000-word `config.MAX_WORDS`) was left as-is, since that cap hasn't
shipped yet in code — the ~1000-word/20-sentence figures are covered only
in the "Planned / in progress" section, consistent with this doc's
current-vs-planned separation. No other stale parallelization or
old-cap references were found on spot-check.
