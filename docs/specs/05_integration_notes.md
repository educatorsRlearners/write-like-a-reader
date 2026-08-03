## Integration Notes — Phase F (final, reconciled)

**Reviewer:** Agent 1R, designated tie-breaker for the `Question`/
`QuestionRecord` data model and the timing schema.
**Scope reviewed:** `00_question_id.md` (SUPERSEDED/retired),
`00_timing_schema.md` (frozen, extended additively for batching + token
tracking), `01_feedback_capture.md`, `02_speed.md` (Phase F rework —
batching replaces parallelization), `03_output_format.md` (hooks
relocated to 02's batch function names).

## Verdict: Clean sign-off. Ready for `docs/specs/04_readme.md`.

**Post-implementation update (`docs/prompts/07_refactor_prompts.md`):**
`03_output_format.md` has since been marked SUPERSEDED. The hook points
below (`_parse_batch_questions`'s per-index loop calling
`_normalize_question_text`, and `_run_batch_checker`'s question-text
assembly for the checker prompt) are still structurally accurate — the
call sites didn't move — but `_normalize_question_text`'s internal
contract changed: it now enforces a 1-sentence cap (not 3) and
warn-only Wh-first-word validation (no more colon-prefix, no more
default-to-`What:` rewrite), and `_run_batch_checker` no longer strips
anything before building the checker prompt (`_CHECKER_STRIP_PREFIX_RE`
was deleted). See `pipeline.py` for the current implementation.

## 1. `03`'s relocated hook points — verified against `02`'s actual text, not just plausibility

Checked both hook points Agent 3 relocated `03_output_format.md` to,
against `02_speed.md`'s current text directly (grepped for the function
names, cross-read the surrounding prose):

- **Normalization hook → `pipeline._parse_batch_questions`'s per-index
  loop.** `02_speed.md` (§1, "Questioner: one call for all sentences")
  genuinely defines this function and describes its body in enough detail
  to pin down where the hook lands: "for each `i` in `range(n)`, look up
  `data.get(str(i))`; if present and a list, parse it the same way
  `_parse_questions` does today (skip non-string/blank entries)..." `03`'s
  diff (`_parse_batch_questions`'s inner `for item in raw_list:` loop,
  `Question(text=item)` -> `Question(text=_normalize_question_text(item))`)
  matches this description structurally. Confirmed genuine, not invented.
  One precision note, not a defect: `02`'s one-line type signature at
  line 113 states `_parse_batch_questions(data, n) -> dict[int,
  list[Question]]` (a bare dict), while `03`'s diff types it as `->
  tuple[dict[int, list[Question]], set[int]]` (dict + failed-indices set).
  This isn't `03` drifting from `02` — it's `03` correctly resolving an
  internal gap in `02`'s own text: `02`'s prose two lines later requires
  distinguishing "index present as `[]`" (valid, no questions — per `02`'s
  own response-contract example, `{"2": []}` is well-formed) from "index
  missing/malformed" (a failed round) — a bare `dict[int, list[Question]]`
  return can't carry that distinction, only a second collection
  (`failed_indices`) can. `03`'s tuple return is the necessary and correct
  completion of what `02`'s own fail-open requirement demands, not a
  contradiction of it.
- **Checker-prompt stripping hook → `_run_batch_checker`'s
  `checker_text_map` construction.** Here the verification is more mixed:
  `02_speed.md` genuinely defines `_run_batch_checker`'s existence, call
  signature (`_run_batch_checker(essay_id, question_map, sentences, n)`,
  confirmed via grep at the `run()` call site and the §3.2 timing-wrapper
  snippet), and its role (produce the `dict[int, list[str]]` that
  `build_batch_checker_prompt` consumes, per that function's own
  documented signature). **But `02` never actually shows
  `_run_batch_checker`'s body, and the specific `checker_text_map`
  variable name/dict-comprehension shape `03`'s diff targets does not
  appear anywhere in `02`'s text** — confirmed by grep, zero hits for
  `checker_text_map` in `02_speed.md`. `03`'s note ("the `checker_text_map`
  construction... [is] 02_speed.md's design, restated here") overstates
  this slightly: it's `03`'s own reconstruction of a conversion step `02`
  never wrote out, not a literal citation. That said, the conversion
  itself is not optional or invented — `02`'s own type signatures make it
  unavoidable (`_run_batch_checker` receives `dict[int, list[Question]]`
  and must feed `build_batch_checker_prompt` a `dict[int, list[str]]`;
  something has to extract `.text` in between), so `03`'s hook lands on a
  real, structurally-forced seam in `02`'s design even though the exact
  variable name is `03`'s own choice rather than `02`'s.

**Net assessment:** both hooks are genuine and will survive contact with
an actual implementation — neither is hanging off a function or contract
that doesn't exist in `02`. The one thing worth a one-line fix (not
blocking) is `03`'s wording around the checker hook, which should say
something closer to "the exact conversion-step shape isn't specified by
`02`; this spec's hook targets the necessary `Question.text` ->
checker-string extraction step wherever `_run_batch_checker`'s
implementation places it" rather than implying it's restating `02`'s own
text verbatim.

## 2. Nothing else in `02` changed to reopen the gap

Re-read `02_speed.md` in full for this pass; its content is unchanged
from the version reviewed in the prior integration pass (same `run()`
control flow, same `_parse_batch_questions`/`_run_batch_checker` call
signatures, same §3 timing/token wiring, same ownership table). Agent 3's
edit was confined to `03_output_format.md`; no corresponding edit was
needed in or made to `02`.

## 3. Everything previously checked remains clean

- `save_llm_call` signature match (param order, names, `sentence_count`
  threaded explicitly at both call sites) — unaffected by this pass,
  still holds.
- `MAX_WORDS`/`MAX_SENTENCES` vs. `01`/`03` — no conflict, unaffected.
- `01_feedback_capture.md`'s `essay_id`/`PipelineResult` constructor
  plumbing — unaffected, still consistent.
- `00_question_id.md` supersession — unaffected, still clean.
- `00_timing_schema.md`'s additive extension — unaffected, `01`'s
  dashboard still composes cleanly against it.

## Summary

All three specs (`01`, `02`, `03`) are now mutually consistent with each
other and with the two Phase A specs (`00_question_id.md`, retired;
`00_timing_schema.md`, frozen-then-extended). The one previously-open gap
— `03`'s hooks targeting pre-batching function names that no longer exist
under `02`'s Phase F rework — is closed: both relocated hooks
(`_parse_batch_questions`'s per-index construction, `_run_batch_checker`'s
question-to-string conversion feeding `build_batch_checker_prompt`) are
genuine, correctly targeted, and functionally sound, with only a minor
wording overstatement in `03`'s own commentary (not a spec defect) noted
above for whoever writes the readme to be precise about. `docs/specs/04_readme.md`
can be written against `00_timing_schema.md`, `01`, `02`, and `03` as they
stand.
