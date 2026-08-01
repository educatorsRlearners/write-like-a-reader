# Speed Spec: Batching + spaCy -> pysbd (Phase F rework)

Status: DESIGN DOC ONLY. No app code is changed by this document. Builds on
`docs/specs/00_timing_schema.md` (`llm_calls` table, now shipped with
`sentence_index` nullable, plus new `sentence_count`/`prompt_tokens`/
`completion_tokens` columns — see §3.1); this spec does not redefine that
schema. Supersedes this file's own prior `ThreadPoolExecutor` design — see
"Phase F rework" note appended to the Reviewer sign-off at the end for
why.

## 0. Grounding: what's actually slow (re-diagnosed)

`pipeline.run()` (`pipeline.py`) loops over sentences produced by
`sentence_split.split_sentences()` and, per sentence `i`, makes up to two
**blocking, synchronous** calls through `llm_client.generate_json()`:

1. **questioner** — `prompts.build_questioner_prompt(sentences_so_far, i)`,
   called unconditionally for every sentence.
2. **checker** — `pipeline._check_answers(questions, next_sentence)` ->
   `prompts.build_checker_prompt(...)`, called for every sentence except the
   last (`i == n - 1`).

Both go through `llm_client._call_model()`, a synchronous `ollama.Client`
call, wrapped in `generate_json()`'s retry loop. With `n` sentences this is
`~2n` fully serial network round-trips.

**Previous version of this spec proposed parallelizing these `~2n` calls
with a thread pool. That proposal is withdrawn based on empirical
measurement, not theory:** a direct test against this machine's actual
Ollama instance ran 3 concurrent requests and 3 sequential warm requests
back to back. The concurrent batch took **longer** wall-clock (7.75s) than
the sequential batch (6.3s), and completion timestamps showed the requests
finishing in a staggered, serialized pattern regardless of client-side
concurrency. **This Ollama instance serializes inference on this hardware
— client-side threading cannot hide that, and would only add thread/queue
overhead on top of it.** If a reviewer is tempted to re-introduce
`ThreadPoolExecutor`/`asyncio`/multiprocessing to fan out per-sentence
calls, that instinct should be checked against this measurement first: it
would very likely deliver zero speedup on this deployment target, for real
measured reasons, not assumed ones.

**Root cause, re-diagnosed:** the ~20s latency is driven by **round-trip
count** (up to `2n` calls per submission), not by insufficient parallelism
— each call carries fixed overhead (connection, model warm state, prompt
processing) that concurrency cannot hide when the server processes requests
serially. **The fix is fewer, larger calls: collapse `~2n` sequential calls
into exactly 2 calls total per submission** (one batch questioner call, one
batch checker call, the second still depending on the first's output).

This redesign is only viable because the input size is being capped small
enough that "the whole submission in one prompt" is actually cheap — see
§1's config changes and §4's token-budget arithmetic.

### Dependency analysis (unchanged conclusion, different consequence)

- **Within one sentence `i`:** the checker step for `i` consumes the parsed
  output of the questioner step for `i` — a real, ordered dependency.
- **Across sentences `i` and `j`:** questioner prompts only need raw
  sentence text (already fully available from `split_sentences()` before
  any LLM call happens); no sentence's questions depend on another
  sentence's generated questions or answers.

This independence claim was correct in the prior version of this spec and
remains correct here — it's *why* batching all sentences into one
questioner call and one checker call is safe (nothing computed for sentence
`j` needs to wait on a per-sentence result for sentence `i`). What changes
is the mechanism: instead of using that independence to fan calls out
concurrently (doesn't help — see above), this design uses it to justify
folding all `n` sentences' worth of questioner work into a **single prompt
and single response**, and likewise for the checker step. **No concurrency
appears anywhere in this design.**

## 1. Batching design in pipeline.py

### Shape: exactly 2 sequential calls per submission, no chunking

```
sentences = split_sentences(text)                 # unchanged, fast, non-LLM
batch_questions = _run_batch_questioner(sentences) # 1 call, covers all n sentences
batch_unanswered = _run_batch_checker(batch_questions, sentences) # 1 call, depends on the questioner call's output
# assemble PipelineResult from batch_questions + batch_unanswered
```

No chunk-boundary logic exists or is needed: with the new `config.MAX_WORDS
= 1000` and `config.MAX_SENTENCES = 20` soft caps (§4), a whole submission
— all sentence text, the prompt template, and the expected JSON response —
comfortably fits in one context window (§4's arithmetic), so there is no
"batch of batches" concept to design. If a draft exceeds the soft caps, the
existing soft-cap notice pattern (warn, don't block — see §4) still lets it
through as a single (larger, slower, but not chunked) call; this spec does
not add hard enforcement or chunking as a fallback.

### Questioner: one call for all sentences

New `prompts.build_batch_questioner_prompt(sentences: list[str]) -> str`,
replacing `build_questioner_prompt`'s per-sentence-with-growing-context
call pattern with a single prompt that presents the whole numbered sentence
list once and asks, for **each** sentence index, what a reader would want
answered having read up through that sentence — i.e. the same "reading
progressively, one sentence at a time" framing the current per-sentence
prompt uses, just resolved for all indices in one response instead of one
index per call. Response contract (index-keyed, not array-position, per
the coordinator's explicit requirement):

```json
{"0": ["question a?", "question b?"], "1": ["question c?"], "2": []}
```

Every sentence index `0..n-1` should have a key, including empty arrays for
sentences that raise no reader questions — but the parser must not assume
that (see fail-open below).

New `pipeline._parse_batch_questions(data, n) -> dict[int, list[Question]]`:
for each `i` in `range(n)`, look up `data.get(str(i))`; if present and a
list, parse it the same way `_parse_questions` does today (skip
non-string/blank entries); if the key is **missing, not a list, or `data`
itself isn't a dict**, that sentence index gets an empty question list and
**that index is recorded as a failed round** — this mirrors today's
per-sentence fail-open (a sentence whose questioner call fails contributes
nothing and is flagged in `failed_rounds`), just applied per-index against
one shared response instead of per-call. A malformed or missing index does
**not** fail the whole submission — every other well-formed index is still
used. This is the "per-sentence fail-open, not whole-submission fail-open"
requirement from the coordinator, applied at the parsing layer.

### Checker: one call for all (question, next-sentence) pairs

Pedagogical scope is unchanged from today: each question is still checked
only against its own sentence's **next sentence** (not the whole rest of
the essay) — per CLAUDE.md's guiding principle, this is a deliberate
pedagogical choice about what "answered" means in this tool, not a
mechanism this spec revisits. Batching only changes how many HTTP round
trips it takes to evaluate all those (question, next-sentence) pairs — one,
instead of up to `n - 1`.

New `prompts.build_batch_checker_prompt(question_map: dict[int,
list[str]], sentences: list[str]) -> str`: for every index `i` in
`question_map` where `i < n - 1` (i.e. `i` has a next sentence — the last
sentence never gets a checker call, unchanged from today), include `i`'s
questions paired with `sentences[i + 1].text`. Response contract, again
index-keyed:

```json
{"0": [true, false], "1": [true]}
```

Each array is **positional within that sentence's own question list**
(position 0 = that sentence's first question, etc.) — only the *sentence*
index needs explicit keying (per the coordinator's requirement, to avoid
ambiguity about which sentence a flat array position belongs to); a given
sentence's own question order is small and already unambiguous, and
keeping the per-question representation to a bare boolean (rather than
echoing the full question text back, as the current per-sentence
`{"question": ..., "answered": ...}` shape does) matters for the
token-budget arithmetic in §4 — echoing every question's full text back in
the checker response would roughly double that call's output size for no
benefit, since the caller already knows the question text by position.

New `pipeline._parse_batch_verdicts(data, question_map) ->
dict[int, list[Question]]` (returns the unanswered subset per sentence
index): for each `i` in `question_map` with `i < n - 1`, look up
`data.get(str(i))`; walk that sentence's own `questions[i]` list by
position exactly as today's `_check_answers` walks `data` by position
(`verdict = arr[j] if j < len(arr) else None`; anything not exactly
`True` — missing entry, wrong type, short array — counts as unanswered).
If `data` itself isn't a dict, or index `i` is missing/not a list/malformed
entirely, **all of that sentence's questions are treated as unanswered**
(today's whole-call fail-open, `return questions`, applied per-index
instead of per-call). The last sentence (`i == n - 1`) is never looked up
here — its questions are unconditionally unanswered, unchanged from today
(`if i == n - 1: unanswered = questions`).

This gives two fail-open layers, matching what exists today at finer
granularity:
- **Call-level:** if the whole batch questioner or batch checker call
  raises `llm_client.LLMError` (backend unreachable, JSON unparseable even
  after retry), every sentence in that batch falls back to today's
  whole-submission-failed behavior for that call (all indices become
  failed-questioner-rounds, or all remaining questions become unanswered,
  respectively) — this is strictly the existing fail-open behavior, just
  now applying to the whole (small, capped) submission instead of one
  sentence, because there's only one call to fail.
- **Index-level (new, needed because of batching):** if the call
  *succeeds* but a specific sentence's key is missing/malformed inside an
  otherwise-valid response, only that sentence is affected — the rest of
  the batch's well-formed indices are used normally. This is the layer
  the coordinator asked for explicitly (§5 of the brief) and did not exist
  before, because before, one call *was* one sentence.

### Retry on malformed JSON: whole-call retry remains acceptable

`llm_client.generate_json`'s existing `retry_prompt` mechanism (one retry
with a stricter follow-up prompt if the model's output isn't parseable
JSON at all) is unchanged and still used for both batch calls. At this
bounded scale (≤20 sentences, ≤1000 words, single call), an occasional
whole-submission retry on totally malformed JSON is an acceptable cost —
it's still at most 2 extra round trips in the worst case, nowhere near the
`~2n` this design eliminates. This spec does not add finer-grained partial
retry (e.g. retrying only the malformed indices) — not needed at this
scale and would reintroduce multi-call complexity for a rare failure mode.

### `run()` signature and control flow

```python
def run(text: str, essay_id: int | None = None, on_progress=None) -> PipelineResult:
    sentences = split_sentences(text)
    n = len(sentences)
    result = PipelineResult(text=text, sentences=sentences)
    if n == 0:
        return result

    if on_progress is not None:
        on_progress(0, 2)  # "step 1 of 2: reading the essay"

    question_map, failed_indices = _run_batch_questioner(essay_id, sentences)
    result.failed_rounds.extend(sorted(failed_indices))

    if on_progress is not None:
        on_progress(1, 2)  # "step 2 of 2: checking answers"

    unanswered_map = _run_batch_checker(essay_id, question_map, sentences, n)

    for i in range(n):
        questions = question_map.get(i, [])
        if not questions:
            continue
        unanswered = questions if i == n - 1 else unanswered_map.get(i, [])
        shown_ids = {id(q) for q in unanswered}
        for q in questions:
            result.question_log.append(QuestionRecord(text=q.text, shown=id(q) in shown_ids))
        if unanswered:
            result.annotations.append(Annotation(
                sentence_index=sentences[i].index,
                start_char=sentences[i].start_char,
                end_char=sentences[i].end_char,
                questions=unanswered,
            ))

    return result
```

`essay_id` is threaded through for the same reason as before (timing
attribution, §3) — `app.py`'s call site changes to
`pipeline.run(draft_text, essay_id=essay_id, on_progress=on_progress)`,
same as the withdrawn design; `essay_id` is already computed earlier in
`get_feedback` via `storage.save_essay`.

**Progress reporting changes shape, not just semantics.** With only 2 LLM
calls total, per-sentence progress (`"reading sentence i of n"`) no longer
has anything granular to report between — `on_progress` now fires twice,
around the two batch calls. `app.py`'s `on_progress` closure needs new
wording (e.g. `"Reading the essay..."` / `"Checking answers..."`) rather
than the current `f"Reading sentence {i + 1} of {n}"`; the `(i, n)` tuple
shape Gradio's `progress()` expects should become `(0, 2)` / `(1, 2)` (or
this spec's implementation may choose to drop numeric progress entirely in
favor of just updating the `desc` string — either is a small, contained
`app.py` change, not prescribed further here).

`_run_batch_questioner`/`_run_batch_checker` are the two functions that
own the actual `generate_json` calls and the timing-wrapper responsibility
described in §3 — they replace `_process_sentence`/`_SentenceOutcome` from
the withdrawn thread-pool design entirely; no per-sentence worker or
outcome dataclass exists in this design.

## 2. spaCy -> pysbd swap (sentence_split.py) — unchanged, unaffected by the rework

This section is carried over as-is from the withdrawn design; batching vs.
threading has no bearing on it. **Explicitly noting: this swap does not
move the latency needle at all** — `split_sentences()` was never the
bottleneck (§0), this is purely the dependency-hygiene change the user
still wants, done independently of the speed fix.

### Verifying spaCy's footprint first

Grepped the whole repo for `spacy`/`nlp`/`doc.sents`/`en_core`: the **only**
reference anywhere is `sentence_split.py`, and within it spaCy is used for
exactly one thing — `doc.sents` boundary detection, via:

```python
_nlp = spacy.load("en_core_web_sm", exclude=["ner", "lemmatizer"])
```

NER and the lemmatizer are already explicitly excluded at load time, and no
other file imports `spacy` or touches `_get_nlp()`/`_nlp`. Confirmed: this
is a pure sentence-boundary-detection dependency, nothing else in the app
reads tokens, POS tags, NER spans, or lemmas from it. Safe to swap
wholesale.

### Replacement design

`pysbd.Segmenter` supports a `char_span=True` mode (paired with
`clean=False`) that returns span objects carrying original-text character
offsets instead of plain segmented strings — exactly what
`Sentence.start_char`/`end_char` need. `clean=False` is required: pysbd's
default cleaning rewrites/strips text, which would desync `start_char`/
`end_char` from the original `text` string that `Annotation` and the
Gradio `HighlightedText` layer index into. Design:

```python
import pysbd
from models import Sentence

_segmenter = None


def _get_segmenter():
    global _segmenter
    if _segmenter is None:
        _segmenter = pysbd.Segmenter(language="en", clean=False, char_span=True)
    return _segmenter


def split_sentences(text: str) -> list[Sentence]:
    spans = _get_segmenter().segment(text)
    return [
        Sentence(
            index=i,
            text=span.sent,
            start_char=span.start,
            end_char=span.end,
        )
        for i, span in enumerate(spans)
    ]
```

This is a near-exact structural mirror of the current function — same
module-level lazy-singleton pattern (`_nlp`/`_get_nlp` ->
`_segmenter`/`_get_segmenter`), same list-comprehension shape, same
`Sentence` construction. `models.Sentence` needs no changes.

**Implementation-phase verification note:** the exact attribute names on
pysbd's `char_span` output object (`span.sent` / `span.start` / `span.end`)
and the minimum pysbd version that ships `char_span` should be confirmed
against whatever version gets pinned in `pyproject.toml` (see §5) before
this lands — this spec's confidence is based on pysbd's documented
`char_span` feature, not a run against an installed copy in this repo (not
currently installed here). If the attribute names differ, only the
list-comprehension body changes; the surrounding structure (lazy singleton,
`Sentence` shape, offset semantics) does not.

### Behavioral risk to flag, not solve here

spaCy's statistical sentence segmenter and pysbd's rule-based segmenter will
not produce byte-identical boundaries on all inputs (e.g. abbreviations,
quoted dialogue, list-like text). Any existing test fixtures or golden
outputs asserting exact sentence counts/boundaries will need review during
implementation. That review is implementation-phase work, not something
this spec resolves — flagging it so it isn't a silent surprise.

(Separately, a Phase C reviewer flagged that reusing `split_sentences` for
counting sentences *within* a short LLM-generated question fragment,
rather than full essay prose, is an untested edge case — carried forward
as a cross-check item, not acted on in this spec; see the Reviewer sign-off
below.)

## 3. Timing + token-usage instrumentation wiring

This section wires `pipeline.py`/`llm_client.py` to the `llm_calls` schema
in `00_timing_schema.md`. Two changes from the withdrawn design's version
of this section: (a) there are now exactly 2 calls per submission instead
of up to `2n`, which changes what "one row" represents, flagged below as a
coordination item; (b) token counts are now captured at the same hook
points as duration/status, not just duration.

### §3.1 `sentence_index`/`sentence_count`: resolved against Agent 1's final schema

Agent 1 has since finalized `00_timing_schema.md` to resolve exactly the
gap flagged in an earlier revision of this section (`sentence_index` no
longer mapping 1:1 to "one row = one sentence" once one call covers a
whole batch). The shipped resolution, which this spec now builds against
directly rather than speculating about:

- **`sentence_index`** is now `INTEGER` (nullable, was `NOT NULL`). For a
  batched call it is `NULL` — there's no single index that describes
  "sentences 0 through 19."
- **`sentence_count`** is a new column, `INTEGER NOT NULL DEFAULT 1`. It
  carries how many sentences the call covered — `1` for old/non-batched
  rows (via the default), and the real sentence count (up to
  `MAX_SENTENCES = 20`) for this design's batched calls. This is the
  column `duration_ms / sentence_count` queries against for a
  per-sentence cost estimate, and it must be populated explicitly by
  every call site below — **leaving it unset silently falls back to the
  column default of `1`, which would misrecord every batched call
  (covering up to 20 sentences) as if it covered exactly one, corrupting
  that per-sentence-cost query.** Both call sites (§3.2 below) pass the
  real `n` (or the real count of sentences covered by the checker call)
  explicitly — never omitted, never left to the default.

### `llm_client.generate_json`: `on_attempt` callback, plus returning token usage

Per `00_timing_schema.md`'s original "Hook points" section, add one
additive, optional parameter for retry counting:

```python
def generate_json(
    prompt: str,
    retry_prompt: str | None = None,
    max_transient_retries: int = 2,
    on_attempt: Callable[[], None] | None = None,
):
```

Invoke `on_attempt()` exactly once per retry actually taken (transient
backoff retry or JSON-parse retry), never on a clean first-try success —
unchanged from the withdrawn design's version of this hook.

**New for this revision:** `_call_model()` currently discards everything
from the Ollama response except `response["message"]["content"]`:

```python
def _call_model(prompt: str) -> str:
    client = _get_client()
    response = client.chat(
        model=config.OLLAMA_MODEL,
        messages=[{"role": "user", "content": prompt}],
        options={"num_predict": 1024},
    )
    return response["message"]["content"]
```

Ollama's chat response already carries `prompt_eval_count` (input tokens)
and `eval_count` (output tokens) natively — no extra API call needed to
get them, they're on the same response object being thrown away today.
`00_timing_schema.md`'s shipped columns for these are named
`prompt_tokens` and `completion_tokens` — this spec uses those exact names
throughout below (not Ollama's own `prompt_eval_count`/`eval_count` field
names) so the callback/storage plumbing matches the schema Agent 1
actually shipped, not Ollama's wire vocabulary. Recommended minimal shape:
extend the `on_attempt`-style callback pattern to a single richer callback
invoked once per logical call resolution (success or failure) rather than
per retry, e.g.:

```python
def generate_json(
    ...,
    on_attempt: Callable[[], None] | None = None,
    on_result: Callable[[int | None, int | None], None] | None = None,
):
    ...
    # after a successful _call_model() call that produced the final `raw`,
    # before returning the parsed data:
    if on_result is not None:
        on_result(last_response.get("prompt_eval_count"), last_response.get("eval_count"))
        # ^ these are Ollama's own response field names; on_result's caller
        # (pipeline.py, below) receives them positionally as
        # (prompt_tokens, completion_tokens) and renames at that boundary
    return data
```

`_call_model` needs to return the full response object (or the two counts)
rather than just `response["message"]["content"]` for `generate_json` to
have them available to pass to `on_result`. Exact plumbing (return a small
`(text, prompt_tokens, completion_tokens)` tuple from `_call_model`, or
thread a mutable "last response" holder through the retry loop) is an
implementation-time call; the requirement this spec is stating is just:
**both hook points (questioner call, checker call) must end up with
`prompt_tokens`/`completion_tokens` alongside `duration_ms`/`status`/
`retries` before persisting**, using those two names by the time they
reach `storage.save_llm_call` (§3.2), since that's what the shipped
schema and function signature expect.

### §3.2 `pipeline.py`: the two call sites

`_run_batch_questioner(essay_id, sentences)` and `_run_batch_checker(essay_id,
question_map, sentences, n)` each wrap their single `generate_json` call
with the **same shared wrapper**, parameterized by `call_type` and
`sentence_count` — not two independently-written copies with a literal
baked in, since that's exactly how a checker failure could get mis-logged
as a questioner row:

```python
def _timed_call(essay_id, call_type, sentence_count, prompt, retry_prompt):
    """Shared by both the questioner and checker call sites. `call_type`
    ('questioner' or 'checker') and `sentence_count` (how many sentences
    this particular call covers) are passed in by the caller — never
    hardcoded here."""
    retries = 0
    def _bump():
        nonlocal retries
        retries += 1

    prompt_tokens = completion_tokens = None
    def _capture(pt, ct):
        nonlocal prompt_tokens, completion_tokens
        prompt_tokens, completion_tokens = pt, ct

    start = time.perf_counter()
    try:
        data = llm_client.generate_json(
            prompt, retry_prompt=retry_prompt, on_attempt=_bump, on_result=_capture,
        )
    except llm_client.LLMError as exc:
        duration_ms = int((time.perf_counter() - start) * 1000)
        _record_call(essay_id, call_type, sentence_count, "failed", retries,
                     duration_ms, prompt_tokens, completion_tokens, str(exc))
        raise
    duration_ms = int((time.perf_counter() - start) * 1000)
    _record_call(essay_id, call_type, sentence_count, "success", retries,
                 duration_ms, prompt_tokens, completion_tokens, None)
    return data
```

Callers still do their own fail-open handling around `_timed_call`
(catching `llm_client.LLMError` the same way `run()` and `_check_answers`
do today — `_timed_call` re-raises after recording, it doesn't swallow):

```python
# _run_batch_questioner:
try:
    data = _timed_call(essay_id, "questioner", n, prompt, prompts.QUESTIONER_RETRY)
except llm_client.LLMError:
    ...  # whole-batch fail-open (§1): every index becomes a failed round

# _run_batch_checker:
try:
    data = _timed_call(essay_id, "checker", checked_sentence_count, prompt, prompts.CHECKER_RETRY)
except llm_client.LLMError:
    ...  # whole-batch fail-open (§1): every question becomes unanswered
```

`sentence_count` differs by call site: the questioner call covers all `n`
sentences; the checker call only ever covers indices with a next
sentence (`0..n-2`), so its `sentence_count` is `checked_sentence_count`
— the number of sentences actually included in that batch's checker
prompt (at most `n - 1`, and possibly fewer if some sentences produced no
questions at all and so had nothing to check). Both are always passed
explicitly — never omitted, per the note in §3.1 about the `DEFAULT 1`
trap.

`_record_call`, matching Agent 1's shipped `storage.save_llm_call`
signature exactly (param order, names, and the `sentence_index`/
`sentence_count` split):

```python
def _record_call(essay_id, call_type, sentence_count, status, retries,
                  duration_ms, prompt_tokens, completion_tokens, error_message):
    if essay_id is None:
        return
    try:
        storage.save_llm_call(
            essay_id,
            None,              # sentence_index — always NULL for a batched call
            sentence_count,
            call_type,
            status,
            retries,
            duration_ms,
            prompt_tokens,
            completion_tokens,
            error_message,
        )
    except Exception:
        logger.warning("Failed to save LLM call timing", exc_info=True)
```

`sentence_index` is always `None` here because nothing in this design
calls `_record_call` for a single-sentence event — both call sites are
whole-batch. (A future non-batched call site, if one is ever added, would
pass a real `sentence_index` and `sentence_count=1`; that's not part of
this design.)

### §3.3 `storage.py`: `save_llm_call`

`storage.save_llm_call`'s real, final signature (Agent 1's, not
independently redefined here) is:

```python
def save_llm_call(essay_id, sentence_index, sentence_count, call_type, status,
                   retries, duration_ms, prompt_tokens=None, completion_tokens=None,
                   error_message=None) -> None:
    init_db()
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "INSERT INTO llm_calls "
            "(essay_id, sentence_index, sentence_count, call_type, status, retries, "
            "duration_ms, prompt_tokens, completion_tokens, error_message, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (essay_id, sentence_index, sentence_count, call_type, status, retries,
             duration_ms, prompt_tokens, completion_tokens, error_message,
             datetime.now(timezone.utc).isoformat()),
        )
```

Column order and names here (`sentence_index`, `sentence_count`,
`prompt_tokens`, `completion_tokens`) are copied directly from
`00_timing_schema.md`'s shipped DDL — not restated independently. This
spec's `_record_call` (§3.2 above) calls this function positionally in
exactly this order; a prior revision of this spec had drifted from it
(wrong param order, missing `sentence_index`/`sentence_count`, and a
`eval_tokens` name that doesn't exist in the real schema — would have
raised `sqlite3.OperationalError: no such column: eval_tokens` at
runtime). Fixed here to match the shipped schema exactly.

### Why "2 rows per submission" needs no concurrency-safety discussion

The withdrawn design's §3 had a subsection justifying why concurrent
threads writing to sqlite via `save_llm_call` was safe. That's moot now —
there is no concurrency anywhere in this design (§0), so there's exactly
one `save_llm_call` write in flight at a time, from the same thread
Gradio's callback runs on. Nothing to reason about here.

## 4. Input caps: `config.MAX_WORDS` / `config.MAX_SENTENCES`, and why they make batching viable

These cap changes are a separate user decision but are load-bearing for
this redesign — batching only works cheaply because the caps guarantee a
submission is small.

### Config changes

```python
# config.py
MAX_WORDS = 1000        # was 3000
MAX_SENTENCES = 20      # new
```

Both are **soft caps** — warn, don't block, reusing the existing
`app.py` pattern (`_word_count_notice`, called before `pipeline.run()`,
never raises `gr.Error`). Add a parallel `_sentence_count_notice`:

```python
def _sentence_count_notice(sentences: list[Sentence]) -> str:
    n = len(sentences)
    if n > MAX_SENTENCES:
        return (
            f"⚠️ This draft has {n} sentences, over the ~{MAX_SENTENCES}-sentence "
            "soft cap. You can still get feedback, but a draft this long can take "
            "longer and may hit rate limits."
        )
    return ""
```

`_sentence_count_notice` needs a sentence list, which today isn't computed
until `pipeline.run()` calls `split_sentences()` internally. Two options
for `get_feedback` in `app.py`: (a) call `sentence_split.split_sentences()`
once in `app.py` before `pipeline.run()`, purely for the notice — cheap
and non-LLM, the minor duplicate work of `pipeline.run()` re-splitting
internally is negligible; or (b) have `pipeline.run()` return the sentence
count/notice-relevant info back out for `app.py` to render post-hoc. This
spec recommends (a) — simplest, keeps `pipeline.run()`'s signature/return
shape stable, mirrors how `_word_count_notice` already runs before
`pipeline.run()` today. Both notices concatenate the same way
`_word_count_notice`/`_status_notice` already do (`"\n\n".join(part for
part in (...) if part)`).

### Why 20 sentences / 1000 words means no chunking is needed

At a 20-sentence ceiling, a whole submission comfortably fits in a single
prompt+response for both the questioner and checker calls — see the
token-budget arithmetic below. This is *why* §1 doesn't need any
chunk-boundary logic: the caps were chosen (by the user, separately) to
keep single-batch calls cheap, and this spec's batching design depends on
that being true.

## 5. Context window: `num_ctx`, and the token-budget arithmetic behind it

### The bug being fixed alongside batching

`_call_model()` today only sets `options={"num_predict": 1024}` — it never
sets `num_ctx`. `ollama show qwen2.5:3b` confirms the model supports a
32768-token context, but without an explicit `num_ctx`, Ollama silently
runs the request at its own default of 2048 tokens. That default was
probably fine for the old per-sentence calls (small prompt, small
response) but is a real risk for this redesign's batched calls, which are
larger by construction. Fix: set `num_ctx` explicitly.

```python
options={"num_predict": 2048, "num_ctx": 8192}
```

(`num_predict` also bumped from `1024` — a single sentence's ~3-4 short
questions fit in 1024 output tokens; ~20 sentences' worth does not, see
arithmetic below.)

### Token-budget arithmetic (approximate — a planning estimate, not a precise tokenizer count)

Using the common rule-of-thumb ratio of roughly 1.3 tokens per English
word (an approximation; qwen2.5's actual BPE tokenizer will differ
somewhat, but this is the right order of magnitude for capacity planning):

**Batch questioner call:**
- Input: essay text, ≤1000 words × ~1.3 ≈ **1300 tokens**, plus sentence
  numbering/prompt template/instructions overhead ≈ **500 tokens** →
  **~1800 tokens in.**
- Output: up to 20 sentences × up to ~4 questions × ~12 tokens/question
  (short who/what/when/where/why/how questions) ≈ **960 tokens**, plus
  JSON structural overhead (keys, braces, quoting) ≈ **negligible, <100
  tokens** → **~1000 tokens out.**
- **Total: ~2800 tokens** — well under the proposed `num_ctx=8192`
  (roughly 3x headroom), and nowhere close to the model's 32768 ceiling.

**Batch checker call:**
- Input: the questions generated above, echoed back into this prompt
  (~960 tokens, same figure as the questioner's output), plus each
  sentence's next-sentence text — across all indices `0..n-2` this is
  effectively most of the essay text again (each sentence except the
  first appears as exactly one other sentence's "next sentence") ≈
  **~1300 tokens**, plus template/instructions overhead ≈ **~400 tokens**
  → **~2700 tokens in.**
- Output: kept deliberately cheap by design (§1) — booleans keyed
  positionally within each sentence's array, not full question echoes —
  up to ~80 questions total (20 sentences × ~4) × ~1-2 tokens per boolean
  plus minimal JSON structure ≈ **~300 tokens out.**
- **Total: ~3000 tokens** — again comfortably under `num_ctx=8192`.

Both calls leave roughly 5000+ tokens of headroom under the proposed
`num_ctx=8192` even at the caps' maximum (1000 words, 20 sentences),
without needing anywhere close to the model's full 32768-token capacity.
`num_ctx=8192` is chosen over something tighter specifically to keep that
margin comfortable against this arithmetic being approximate (real
tokenization, verbose model output, or unusually long individual sentences
could all push the real count somewhat above this estimate).

## 6. Ownership notes

| File | This spec owns | This spec depends on / does not touch |
|---|---|---|
| `pipeline.py` | Full rewrite of `run()`'s control flow (2-call batch shape, no thread pool); new `_run_batch_questioner`, `_run_batch_checker`, `_parse_batch_questions`, `_parse_batch_verdicts`, `_record_call`; removal of the withdrawn design's `_process_sentence`/`_SentenceOutcome` (never implemented, so nothing to actually revert in real code) | `models.py` types unchanged (no new fields needed) |
| `llm_client.py` | Additive `on_attempt` and `on_result` params on `generate_json`; `_call_model` changed to expose `prompt_eval_count`/`eval_count` up to the caller instead of discarding them; `options` dict gains explicit `num_ctx=8192` (and bumps `num_predict` to `2048`) | Retry/backoff logic, `LLMError`, module-level `_client` singleton all unchanged; no thread-safety concerns since there's no concurrency in this design |
| `prompts.py` | New `build_batch_questioner_prompt`, `build_batch_checker_prompt` | `build_questioner_prompt`/`build_checker_prompt` (the old per-sentence builders) become dead code under this design — implementation should remove them, not keep both, to avoid confusion about which is live |
| `sentence_split.py` | Full replacement of spaCy with pysbd (whole-file rewrite, same public `split_sentences` signature) — unchanged from prior version of this spec | `models.Sentence` unchanged |
| `storage.py` | New `save_llm_call` function, matching Agent 1's shipped signature exactly (`essay_id, sentence_index, sentence_count, call_type, status, retries, duration_ms, prompt_tokens=None, completion_tokens=None, error_message=None`); `init_db()` grows to include the `llm_calls` DDL | Authoritative `llm_calls` column list/types/order **not owned here** — owned by `00_timing_schema.md` (Agent 1), copied verbatim in §3.3 |
| `pyproject.toml` | Swap `"spacy>=3.7"` for a pinned `pysbd` dependency | Pre-approved; no other dependency changes in scope |
| `config.py` | `MAX_WORDS` 3000 -> 1000; new `MAX_SENTENCES = 20`; removal of the withdrawn design's `PIPELINE_MAX_WORKERS` (not needed, no thread pool) | `OLLAMA_*`/`DB_PATH` unchanged |
| `app.py` | Call-site change to `pipeline.run(draft_text, essay_id=essay_id, on_progress=on_progress)`; new `_sentence_count_notice`, wired alongside `_word_count_notice`; `on_progress` closure rewritten for the 2-step batch shape instead of per-sentence progress; one extra `split_sentences()` call before `pipeline.run()` to feed `_sentence_count_notice` (§4) | Everything else in `app.py` untouched |
| `tests/test_pipeline.py` | Full rework — the existing per-sentence `.pop(0)`-queue mocks assumed one `generate_json` call per sentence; under this design there are exactly 2 calls total (one questioner, one checker) covering all sentences, so mocks need to return single batch-shaped JSON objects (`{"0": [...], "1": [...], ...}`) instead of per-sentence queues. This is a bigger rework than the withdrawn design's mock-ordering fix, but the withdrawn design was never implemented, so there's nothing to "re-revert" in actual test code — this is the one and only test rework needed | Test *behavior being verified* (which sentence gets which annotation, `question_log` order, `failed_rounds` contents, fail-open on backend failure) is conceptually unchanged; only fixture shape changes |
| `tests/test_llm_client.py` | New tests for `on_attempt` (retry counting, unchanged from withdrawn design) and new tests for `on_result`/token-count plumbing (asserts `prompt_eval_count`/`eval_count` are passed through from a mocked Ollama response) | Existing tests unchanged — both new params are optional and default to `None` |
| `00_timing_schema.md` (Agent 1) | — | This spec treats it as authoritative for column definitions (`sentence_index`/`sentence_count`/`prompt_tokens`/`completion_tokens`, shipped); does not modify it |

## 7. Open items for implementation, not blocking this spec

- pysbd's exact `char_span` attribute names/minimum version (§2) need a
  quick confirmation against the pinned version once `pysbd` is actually
  installed.
- Any existing sentence-boundary test fixtures need review after the pysbd
  swap for boundary differences vs. spaCy (§2, behavioral risk note).
- The token-budget arithmetic in §5 is a planning estimate against a
  1.3-tokens/word heuristic, not a measurement against qwen2.5's actual
  tokenizer — worth a quick sanity check with a real long draft once
  implementation starts, though the ~3x headroom to `num_ctx=8192` gives
  meaningful margin for error.
- `_call_model`'s exact refactor shape for exposing `prompt_eval_count`/
  `eval_count` (return tuple vs. mutable holder vs. something else) is
  left to implementation, per §3.
- Reusing `split_sentences` to count sentences *within* a short
  LLM-generated question fragment (not full essay prose) remains an
  untested edge case per a Phase C reviewer note — unrelated to this
  rework, carried forward unresolved.

## Reviewer sign-off

Reviewed by Agent 2R. Core independence claim (sentences are
parallelizable across their questioner->checker chains; only the chain
within one sentence is sequential) was checked against the real
`pipeline.py` code and confirmed correct. The timing-instrumentation
wiring was reviewed and found solid with no changes requested at that
time.

Two issues were raised on the (now-withdrawn) thread-pool version of this
spec and addressed in a prior revision:

1. `ollama.Client` thread-safety was asserted, not verified — flagged as
   an open risk with a thread-local fallback option.
2. `tests/test_pipeline.py`'s pop-order mocks would have become
   nondeterministic under concurrent execution — a mock-strategy rework
   was spec'd (§3.5 in that revision).

A Phase C integration check then found, and a follow-up revision fixed,
a real blocking conflict with `00_question_id.md`'s (then-frozen)
`Question.id` stamping requirement — subsequently reverted when
`01_feedback_capture.md` was redesigned around `(essay_id,
sentence_index)` instead of per-question ids and `00_question_id.md` was
marked SUPERSEDED.

### Phase F rework: parallelization withdrawn, replaced with batching

All of the above (thread pool, `_SentenceOutcome`, per-sentence worker,
`PIPELINE_MAX_WORKERS`, the `ollama.Client` thread-safety open risk, and
the associated `tests/test_pipeline.py` mock-ordering rework) is
**superseded by this revision**, not merely amended. Reason: an empirical
test against this machine's real Ollama instance showed concurrent
requests taking *longer* wall-clock than sequential ones (7.75s vs.
6.3s), with staggered completion times indicating the server serializes
inference regardless of client-side concurrency — the thread-pool design
would have delivered zero measured speedup, for a hardware reason no
amount of client-side engineering fixes. The `ollama.Client` thread-safety
open risk is moot (nothing shares the client across threads anymore).
The `tests/test_pipeline.py` mock-ordering fix is moot (there's no
ordering to worry about — mocks now need a full shape rework instead,
per §6's ownership table, since call granularity changed from
one-per-sentence to one-per-submission).

Root cause was re-diagnosed as round-trip *count*, not missing
parallelism: this revision collapses `~2n` sequential calls into exactly
2 (batch questioner, batch checker, second depends on first's output),
made viable by new hard-soft input caps (`MAX_WORDS` 1000, new
`MAX_SENTENCES` 20, §4) that keep a whole submission cheap enough to fit
one prompt+response. New in this revision: explicit `num_ctx`/
`num_predict` tuning with token-budget arithmetic (§5, fixing a real bug
where `num_ctx` was never set and silently ran at Ollama's 2048 default
against a model that supports 32768); index-keyed batch response
contracts with two-layer fail-open — call-level (existing) and index-level
(new, needed because one call now covers many sentences) — so a malformed
or missing single sentence's data in a batch response degrades that one
sentence, not the whole submission (§1); and token-usage capture
(Ollama's `prompt_eval_count`/`eval_count`, already present on the
response and previously discarded, mapped to the schema's
`prompt_tokens`/`completion_tokens` columns) alongside duration/status at
the same hook points (§3), built against Agent 1's shipped revision of
`00_timing_schema.md` (`sentence_index` nullable, new `sentence_count`
column) rather than speculating ahead of it.

The spaCy -> pysbd swap (§2) is carried over unchanged and is explicitly
noted as orthogonal to the latency fix — it was never the bottleneck and
remains in scope purely because the user still wants the dependency
swapped.

### Follow-up fix: §3 drift from Agent 1's shipped `00_timing_schema.md`

Reviewed by Agent 2R against Agent 1's now-final `00_timing_schema.md`
(this file previously only speculated about how the `sentence_index`
conflict would be resolved; Agent 1 has since shipped the resolution).
Four concrete bugs found, all fixed in this revision:

1. **Signature mismatch.** §3.3's `save_llm_call` now matches Agent 1's
   real signature exactly: `save_llm_call(essay_id, sentence_index,
   sentence_count, call_type, status, retries, duration_ms,
   prompt_tokens=None, completion_tokens=None, error_message=None)` —
   previously shown with a different, invented param order/set that
   dropped `sentence_index`/`sentence_count` entirely.
2. **`sentence_count` now threaded through explicitly, never omitted.**
   §3.1 spells out why leaving it unset is a real data-corruption risk
   (silently falls back to the column's `DEFAULT 1`, misrecording every
   batched call — up to 20 sentences — as covering exactly one). §3.2's
   call sites now pass the real sentence count explicitly: `n` for the
   questioner call, `checked_sentence_count` (sentences actually included
   in that batch, at most `n - 1`) for the checker call.
3. **`eval_tokens` renamed to `completion_tokens` throughout.** The
   previous revision used a name that doesn't exist in the real schema —
   as written it would have raised `sqlite3.OperationalError: no such
   column: eval_tokens` at runtime, not just been a documentation
   mismatch. Every mention in §3 (the `on_result` callback, `_capture`,
   `_record_call`, `save_llm_call`) now says `completion_tokens`.
4. **`call_type` is no longer a hardcoded literal in the shared wrapper.**
   §3.2's `_timed_call` now takes `call_type` as a parameter and both call
   sites (`_run_batch_questioner`, `_run_batch_checker`) pass their own
   value in — previously the shared snippet hardcoded `"questioner"` while
   the prose claimed it was reused as-is for the checker call site, which
   would have mis-logged every checker failure as a questioner row.

§3.1 (formerly "Coordination flag") is rewritten from "flagging an
unresolved conflict for Agent 1" to "documenting the resolution Agent 1
shipped" — `sentence_index` nullable, `sentence_count` new — since that
coordination is no longer open. No changes were needed outside §3; §1,
§2, §4, §5, and §6 (aside from the `save_llm_call`/`00_timing_schema.md`
ownership-table rows, updated to match) are unaffected by this fix.
