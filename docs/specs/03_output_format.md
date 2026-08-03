# Spec: Question Output Format (length cap + Wh-word prefix)

**Status: SUPERSEDED (post-implementation revision, `docs/prompts/07_refactor_prompts.md`).**
This spec's colon-prefix contract (`"Who: Who says that?"`) has been
replaced. The questioner prompt was hand-edited to ask for natural,
unprefixed questions (`"Who says that?"`), and `pipeline._normalize_question_text`
was rewritten to match: it now enforces a **1-sentence cap** (not 3) and
**validates** that the question's own first word is a Wh-word
(who/what/when/where/why/how), logging a warning and passing the text
through **unchanged** if not — it no longer rewrites or prepends a default
prefix. `_WH_PREFIX_RE`, `_DEFAULT_PREFIX`, and `_CHECKER_STRIP_PREFIX_RE`
(the checker-prompt prefix-stripping step in Section 6) have all been
deleted outright — there's no colon-prefix left to strip, so `q.text` goes
to the checker unchanged. See `pipeline.py`'s `_normalize_question_text`
and `_run_batch_checker` for the current implementation. Everything below
this notice documents the retired design — kept for history, not
implemented.

---

**Status:** Spec only; no app code changes yet.
**Owner:** This spec (`03_output_format.md`) owns the questioner-prompt
instruction text (`prompts.build_batch_questioner_prompt`, formerly
`build_questioner_prompt`), and the normalization logic hooked into
`pipeline._parse_batch_questions` (formerly `_parse_questions`) and the
checker-prompt prefix-stripping hooked into `pipeline._run_batch_checker`
(formerly `_check_answers`) — see the "Reconciled with Phase F batching
rewrite" note at the end of the Reviewer sign-off for why the target
function names changed. It does not depend on any other spec's changes to
`Question`/`QuestionRecord` — `docs/specs/00_question_id.md`, which
previously added an `id` field these diffs were written against, has since
been marked SUPERSEDED (the feedback spec was redesigned to key on
`essay_id` + `sentence_index` rather than a per-`Question` id). References
to that spec below have been removed; this spec's diffs are written
against `Question`/`QuestionRecord` as they exist in `models.py` today
(just `text: str`, no `id` field).

## Problem

`docs/prompts/06_todo_list.md` (lines 12-15) requires two constraints on
every generated question's `text`:

1. No more than three sentences per question.
2. The text always starts with its Wh-word category as a literal prefix —
   `Who:`, `What:`, `When:`, `Where:`, `Why:`, or
   `How many/much/long/often:` (whichever "how ___" variant fits) — matched
   to whatever the question is actually asking about.

Today, `build_questioner_prompt` (prompts.py) asks the model for "3 to 4
short who/what/when/where/why/how questions" but gives no explicit length
cap and no formatting requirement, and `_parse_questions` (pipeline.py)
constructs `Question(text=item)` directly from whatever string the LLM
returned, with no post-processing. Both gaps need to close: a prompt-level
instruction (best effort, not guaranteed) and a server-side normalization
step (the actual guarantee).

## 1. Questioner prompt changes (`prompts.build_questioner_prompt`)

Add an explicit formatting block to the prompt, and update the worked
example so it demonstrates the required shape (the current example's bullet
list — "How do you know?", "Who says that?" etc. — has no prefixes and
would model the wrong behavior if left as-is).

Insert after the existing "Only ask questions a real reader would actually
have..." paragraph and before the worked example:

```
Formatting rules for every question you write:
- Start the question with its category as a literal prefix, followed by a
  colon and a space: "Who:", "What:", "When:", "Where:", "Why:", or
  "How many/much/long/often:" (pick whichever "how" variant actually fits --
  e.g. "How many:", "How long:", "How often:" -- rather than always writing
  the full slash-separated list). Use the prefix that matches what the
  question is actually asking about, not just the first Wh-word that comes
  to mind.
- Keep each question to three sentences or fewer. One sentence is fine and
  often best; use a second or third only when necessary framing (e.g. "X
  says Y. Where's that from?").
```

And rewrite the worked example to show compliant output:

```
For example, if a writer wrote, 'Social media has changed the way people
communicate.' Some valid questions would be:
    - How: How did it change the way people communicate? For better or worse?
    - Who: Who says that?
    - When: When did social media change the way people communicate?
```

(Kept 3 examples instead of the original 4 to fit `How do you know?` into
the `How:` category-merge below — see Note.)

**Note on prefix vocabulary vs. the todo list's wording:** the todo list
writes `"How many/much/long/often/etc"` as one category. The prompt above
keeps that as a single instruction line (so the model doesn't have to
memorize six separate categories) but tells the model to substitute in
context (`How many:`, `How long:`, ...) rather than emit the literal
slash-joined string on every question — that string reads badly inline
("How many/much/long/often: How many hours...?"). The normalization regex
in Section 2 accounts for this by accepting any `How <word>:` prefix, not
just an exact match against the todo list's slash-joined text. If the
reviewer wants the literal joined string enforced byte-for-byte instead,
that's a one-line change to both the prompt text and the regex — flagging
it as a decision point rather than assuming.

The JSON response instruction at the end of the prompt is unchanged.

## 2. Normalization step (`pipeline.py`)

LLM instruction-following on both constraints is best-effort, not
guaranteed, so `_parse_questions` needs a server-side safety net. Proposed
new helper, called from `_parse_questions`:

```python
import re

# Strip a leading bullet/markdown marker ("- ", "* ", "**") before matching
# the category, since the questioner may echo the worked example's bullet
# formatting (e.g. "- Who: ..." or "**Who:** ...") even though the JSON
# response instruction asks for a bare array of strings.
_LEADING_MARKUP_RE = re.compile(r"^[\-\*\s]+")
# `how\s+\w+(?:\s+\w+)?` covers both one-word ("how long", "how often") and
# two-word ("how much longer", "how many times") "how" categories.
_WH_PREFIX_RE = re.compile(
    r"^\**(who|what|when|where|why|how\s+\w+(?:\s+\w+)?)\**\s*:\**\s*", re.IGNORECASE
)
_DEFAULT_PREFIX = "What"


def _normalize_question_text(raw: str) -> str:
    """Enforce the Wh-prefix and 3-sentence constraints on one question string.

    Returns the normalized text; never returns an empty string for
    non-empty input (falls back to a `What:` prefix rather than dropping
    the question -- see rationale below).
    """
    text = _LEADING_MARKUP_RE.sub("", raw.strip()).strip()

    match = _WH_PREFIX_RE.match(text)
    if match:
        prefix = match.group(1)
        body = text[match.end():].strip()
    else:
        prefix = _DEFAULT_PREFIX
        body = text

    # Re-title-case the category so "who:" -> "Who:", "HOW MANY:" -> "How many:".
    prefix = prefix[:1].upper() + prefix[1:].lower()

    sentences = [s.text.strip() for s in sentence_split.split_sentences(body) if s.text.strip()]
    if len(sentences) > 3:
        sentences = sentences[:3]
    body = " ".join(sentences) if sentences else body

    return f"{prefix}: {body}"
```

Design decisions:

- **Prefix check** — `_LEADING_MARKUP_RE` first strips leading
  bullet/markdown decoration (`- `, `* `, stray whitespace), then
  `_WH_PREFIX_RE` matches a leading `<word(s)>:` where the first word is a
  recognized Wh-word, or `how` followed by one or two more words (`how
  many`, `how long`, `how often`, `how much longer`, `how many times`, ...),
  tolerating `**bold**` markdown wrapping the category itself
  (`**Who:**`), case-insensitive. This closes two gaps found in review:
  (a) the worked example in the prompt uses bullet-dash formatting, so a
  model echoing that style verbatim (`"- Who: ..."`) would otherwise fail
  to match and get miscategorized as `What:`; (b) two-word "how" categories
  (`"How much longer:"`) weren't captured by a single-`\w+` pattern. If the
  LLM already complied (expected, common case), the match is a
  no-op pass-through of the prefix it wrote (re-cased for consistency). If
  it didn't comply (no recognizable prefix at all), we **coerce** by
  prepending `"What:"` rather than rejecting/dropping the question outright.
  Rationale: `_check_answers` and the annotation UI both depend on having
  *some* question text to show the student; silently dropping a
  reader-relevant question because the model forgot a colon is a worse
  failure mode than mislabeling its category. `What:` is the safest default
  because it's the most category-agnostic Wh-word.
- **Sentence counting** — reuses `sentence_split.split_sentences` rather
  than inventing a second splitter, per the todo list's preference. This
  does mean each question string pays for a call into whatever segmenter
  backs `split_sentences`; that function already loads a cached shared
  singleton (module-level `_nlp` in sentence_split.py today), so the
  marginal cost per question is one call on a short string, not a model/
  pipeline reload. Given each pipeline round already makes an LLM call per
  sentence, a handful of extra segmenter calls on ~1-3 short questions is
  not a meaningful cost.

  **Dependency on 02_speed.md's spaCy -> pysbd swap:** 02_speed.md proposes
  replacing spaCy with pysbd inside `sentence_split.split_sentences`,
  preserving the function's signature and `Sentence` shape but explicitly
  warning that pysbd and spaCy won't produce byte-identical sentence
  boundaries on abbreviations, quoted dialogue, or list-like text. This
  normalization step is *more* exposed to that risk than 02's own use
  case: 02 runs the segmenter over full essay prose, while this step runs
  it over short, fragment-y, LLM-generated interrogative text (a single
  question, often with an embedded abbreviation, quote, or list-like
  clause) — exactly the input shapes 02 flags as divergence-prone, and in
  a context where a boundary miscount directly changes normalization
  behavior (whether a question gets truncated at 3 sentences or not, and
  where). This spec's 3-sentence truncation is therefore only as accurate
  as whichever segmenter `split_sentences` wraps at the time this code
  runs — if 02 lands first, this step's behavior should be re-validated
  against pysbd specifically on short interrogative fragments, since that
  combination is untested territory for pysbd (02_speed.md's own examples
  and testing are essay-prose-shaped, not question-shaped). This is a
  known, accepted cross-spec dependency, not a blocker — `split_sentences`'s
  public contract (`text -> list[Sentence]`) is what this step relies on,
  and 02 preserves that contract regardless of which library sits behind
  it.

  If this spec is applied somewhere with tighter perf constraints or where
  the pysbd-divergence risk above is unacceptable, a regex-based
  sentence-boundary count (splitting on `[.!?]` followed by whitespace)
  would be the fallback, but it's not the recommended first choice —
  `sentence_split.split_sentences` is already the project's single source
  of truth for sentence boundaries, and duplicating that logic risks a
  *third* disagreeing implementation on top of the spaCy/pysbd divergence
  02 already flags.
- **Truncation, not rejection, for over-length questions** — same
  rationale as the prefix case: keep the first 3 sentences rather than
  discard the whole question. A question that runs long because the model
  over-explained is still likely to have its actual ask in the first
  sentence or two.
- **Empty-after-normalization edge case** — if `body` becomes empty (e.g.
  raw input was only a prefix, `"Who:"`, with nothing after it), `body`
  falls back to the pre-split stripped text unchanged (see `body = " ".join(sentences) if sentences else body`), so we never emit
  `"What: "` with a trailing empty body. `_parse_batch_questions`'s
  existing `item.strip()` truthiness check upstream (see Section 3; same
  check `_parse_questions` used to run, now inside the per-index loop)
  already filters fully-empty raw strings before this helper runs.

## 3. `_parse_batch_questions` / `pipeline.run()` diff

**Retargeted for the Phase F batching rework (`02_speed.md`).** That spec
replaces the per-sentence `_parse_questions(data) -> list[Question]` /
`{"questions": [...]}` contract with a single batch call whose response is
index-keyed (`{"0": ["question a?", ...], "1": [...], ...}`), parsed by
`pipeline._parse_batch_questions(data, n) -> dict[int, list[Question]]`.
Per 02's own description of that function: for each `i` in `range(n)`,
look up `data.get(str(i))`; if present and a list, parse it the same way
`_parse_questions` used to (skip non-string/blank entries) — **that
per-item construction step is this spec's hook point**, unchanged in kind
from the old design, just relocated into the new function's inner loop.
If the key is missing/not a list/`data` isn't a dict, that index gets an
empty question list and is recorded as a failed round (02's concern, not
this spec's — untouched here).

Against `Question`/`QuestionRecord` as they exist in `models.py` today
(`text: str` only) and `02_speed.md`'s `_parse_batch_questions` shape:

```diff
+import re
+
 import llm_client
 import prompts
+import sentence_split
 from models import Annotation, PipelineResult, Question, QuestionRecord
 from sentence_split import split_sentences


+_LEADING_MARKUP_RE = re.compile(r"^[\-\*\s]+")
+_WH_PREFIX_RE = re.compile(
+    r"^\**(who|what|when|where|why|how\s+\w+(?:\s+\w+)?)\**\s*:\**\s*", re.IGNORECASE
+)
+_DEFAULT_PREFIX = "What"
+
+
+def _normalize_question_text(raw: str) -> str:
+    text = _LEADING_MARKUP_RE.sub("", raw.strip()).strip()
+    match = _WH_PREFIX_RE.match(text)
+    if match:
+        prefix, body = match.group(1), text[match.end():].strip()
+    else:
+        prefix, body = _DEFAULT_PREFIX, text
+    prefix = prefix[:1].upper() + prefix[1:].lower()
+
+    sentences = [
+        s.text.strip() for s in sentence_split.split_sentences(body) if s.text.strip()
+    ]
+    if len(sentences) > 3:
+        sentences = sentences[:3]
+    body = " ".join(sentences) if sentences else body
+
+    return f"{prefix}: {body}"
+
+
 def _parse_batch_questions(data, n) -> tuple[dict[int, list[Question]], set[int]]:
     questions_by_index: dict[int, list[Question]] = {}
     failed_indices: set[int] = set()
     for i in range(n):
         raw_list = data.get(str(i)) if isinstance(data, dict) else None
         if not isinstance(raw_list, list):
             questions_by_index[i] = []
             failed_indices.add(i)
             continue
         parsed = []
         for item in raw_list:
             if isinstance(item, str) and item.strip():
-                parsed.append(Question(text=item))
+                parsed.append(Question(text=_normalize_question_text(item)))
         questions_by_index[i] = parsed
     return questions_by_index, failed_indices
```

(The `_parse_batch_questions` skeleton above — the `data.get(str(i))`
lookup, per-index fail-open into `failed_indices`, overall return shape —
is 02_speed.md's design, restated here only as far as needed to show
where this spec's one-line hook fits; 02 owns that function's actual
contract. This spec's only contribution to it is the same substitution as
before: `Question(text=item)` -> `Question(text=_normalize_question_text(item))`,
now inside the per-index inner loop instead of the old flat loop.)

Nothing else about `_parse_batch_questions` changes because of this spec —
it still returns one `Question` list per sentence index and still skips
non-string / blank-after-strip items; the index-level fail-open bookkeeping
is entirely 02's concern.

`pipeline.run()` needs **no changes from this spec**, under either the old
or the batched design. Per 02_speed.md's `run()` sketch (§1), it calls
`_run_batch_questioner` (which calls `_parse_batch_questions` internally)
once, and everything downstream (`_run_batch_checker`, `question_log`
construction, `Annotation` building) operates on `Question.text` opaquely —
it never inspects the string's shape. This spec's normalization is fully
contained inside `_parse_batch_questions`'s per-item construction step, so
it's a self-contained change confined to that inner loop and doesn't touch
`pipeline.run()`'s body, `_run_batch_questioner`'s retry/fail-open handling,
or any other part of 02's batching design.

## 4. Downstream: app.py / highlight.py need no changes

Confirmed by inspection:

- `app.py` line 113: `lines = [f"- {q.text}" for q in annotation.questions]`
- `highlight.py` line 65: `pieces.append(f" [{question.text}]")`

Both interpolate `q.text` / `question.text` verbatim with no parsing,
truncation, or assumptions about its internal structure. Since
`_normalize_question_text` guarantees the `"<Prefix>: <body>"` shape (and
the length cap) before a `Question` object ever exists, both render sites
automatically pick up the new format with zero code changes — e.g. `- Who:
Who says that?` and ` [Who: Who says that?]` respectively. This is the
main benefit of enforcing the format at construction time in
`_parse_questions` rather than at render time: one normalization point,
two consumers get it for free, and any future consumer (export format,
feedback UI, etc.) does too.

## 5. Ownership notes

**Retargeted for the Phase F batching rework (`02_speed.md`):** the
function names below are 02's post-rework names
(`build_batch_questioner_prompt`, `_parse_batch_questions`,
`_run_batch_checker`), not the pre-rework `build_questioner_prompt`/
`_parse_questions`/`_check_answers` this spec originally targeted. 02 owns
those functions' actual contracts (batch response shape, fail-open
granularity, retry/timing wiring); this spec owns only the specific
one-line hooks inside them called out below.

**This spec owns:**
- The new formatting-rules paragraph and revised worked example inside
  `prompts.build_batch_questioner_prompt`'s returned string (prompts.py) —
  formerly `build_questioner_prompt`, superseded by 02_speed.md.
- `_normalize_question_text` (new helper, pipeline.py) and the one-line
  change inside `_parse_batch_questions`'s per-index inner loop
  (`Question(text=item)` -> `Question(text=_normalize_question_text(item))`)
  — formerly the same substitution inside `_parse_questions`'s flat loop,
  relocated per 02_speed.md's index-keyed batch parsing.
- The prefix-stripping change inside `_run_batch_checker` (pipeline.py,
  see below) that strips the `"<Category>: "` prefix before building the
  `dict[int, list[str]]` passed to `build_batch_checker_prompt` — formerly
  the same change inside `_check_answers`, superseded by 02_speed.md.

**This spec depends on no other spec's changes.** `Question`/
`QuestionRecord` are used here exactly as they exist in `models.py` today
(`text: str` only, no `id` field). `storage.save_questions`'s return
contract is untouched and unrelated to this spec's scope (`Question.text`
formatting only).

**Not touched by either spec, confirmed safe:** app.py's `on_select`
rendering, highlight.py's `annotated_draft_text`.

## 6. Checker prompt: strip the prefix before sending to the checker LLM

Resolved (previously an open question; reviewer agreed with stripping).
**Retargeted for the Phase F batching rework (`02_speed.md`).** The old
hook, `_check_answers`, no longer exists under 02's design — it's
superseded by `pipeline._run_batch_checker(essay_id, question_map,
sentences, n)`, which assembles a `dict[int, list[str]]` of
(sentence-index -> that sentence's question texts) and hands it to
`prompts.build_batch_checker_prompt(question_map, sentences)` for a single
batched call, instead of `_check_answers` building one `[q.text for q in
questions]` list per sentence per call. The prefix-stripping requirement
is unchanged in kind — sending the raw prefixed text (`"Who: Who says
that?"`) repeats the category word and risks confusing weaker local models
reading the numbered/keyed list — only the assembly point moves.

`Question.text` itself keeps its prefix (that's the whole point of this
spec — the student-facing rendering in app.py/highlight.py needs it). Only
the *checker-facing* copy strips it, at the point `_run_batch_checker`
builds the `dict[int, list[str]]` argument to
`build_batch_checker_prompt`:

```diff
+_CHECKER_STRIP_PREFIX_RE = _WH_PREFIX_RE  # same pattern, reused as-is
+
+
 def _run_batch_checker(essay_id, question_map: dict[int, list[Question]],
                         sentences, n) -> dict[int, list[Question]]:
     """Return, per sentence index < n - 1, the subset of that index's
     questions NOT answered by the next sentence. Fails open per 02_speed.md
     (whole-call and per-index fail-open both apply; unaffected by this
     spec's change below).
     """
-    checker_text_map = {
-        i: [q.text for q in qs]
-        for i, qs in question_map.items()
-        if i < n - 1 and qs
-    }
+    checker_text_map = {
+        i: [_CHECKER_STRIP_PREFIX_RE.sub("", q.text, count=1) or q.text for q in qs]
+        for i, qs in question_map.items()
+        if i < n - 1 and qs
+    }
     prompt = prompts.build_batch_checker_prompt(checker_text_map, sentences)
     ...  # _timed_call / _parse_batch_verdicts, unchanged by this spec
```

(The `checker_text_map` construction and the surrounding
`_run_batch_checker` shape are 02_speed.md's design, restated here only as
far as needed to show where this spec's hook fits; 02 owns that function's
actual contract, fail-open behavior, and the `_timed_call`/
`_parse_batch_verdicts` plumbing around it.)

`_CHECKER_STRIP_PREFIX_RE` is the same `_WH_PREFIX_RE` used in
normalization — by construction every `Question.text` reaching this point
already has a recognized prefix (normalization guarantees it, now applied
inside `_parse_batch_questions` per Section 3), so the substitution always
matches and always strips exactly the category. The `or q.text` fallback
guards only the theoretical case of a `Question` constructed outside
`_parse_batch_questions` (e.g. directly in a test) with no matching
prefix, so stripping never produces an empty string sent to the checker.
This only touches the *local dict* passed into `build_batch_checker_prompt`
— `question_map` (and each `Question.text` inside it) is unchanged, so
`question_log`/`annotations` still get the prefixed text.

## Fixture: sentence-count boundary case with an abbreviation

Given the pysbd-dependency risk noted above, a concrete worked example is
worth pinning down now so it can be re-run once 02_speed.md's segmenter
swap lands. Input (hypothetical raw LLM output, already has a valid
prefix, 4 sentences — one over the cap):

```
raw = "How long: The article, published Jan. 5, doesn't say. Why not?"
```

Expected behavior of `_normalize_question_text(raw)`:

1. No leading markup to strip.
2. `_WH_PREFIX_RE` matches `"How long:"` -> `prefix = "How long"`,
   `body = "The article, published Jan. 5, doesn't say. Why not?"`.
3. `sentence_split.split_sentences(body)` must resolve `"Jan. 5"` as an
   abbreviation, not a sentence boundary, to correctly count this as
   **2** sentences (`"The article, published Jan. 5, doesn't say."` and
   `"Why not?"`) — both under the 3-sentence cap, so nothing gets
   truncated and `body` is rejoined unchanged.
4. Result: `"How long: The article, published Jan. 5, doesn't say. Why not?"`
   (unchanged from input, modulo the prefix re-casing, which is already
   correctly cased here).

**Why this is the risk case, concretely:** with spaCy (today's segmenter),
`"Jan."` is a known abbreviation and step 3 resolves as expected. If pysbd
(02_speed.md's proposed replacement) instead splits on the period in
`"Jan."` — plausible, since pysbd's abbreviation handling is
English-general-purpose rather than tuned to this corpus — `body` would
count as **3** sentences (`"The article, published Jan."`, `"5, doesn't
say."`, `"Why not?"`), still under the cap in this specific example by
coincidence, but a slightly longer version of the same input (one more
clause before the abbreviation) would flip from "3, keep everything" to
"4, truncate and silently drop the trailing `Why not?"` clause — a
behavior change purely from the segmenter swap, with no change to this
spec's own code. This fixture should become an actual unit test
(`test_normalize_question_text` or similar) once pysbd lands per
02_speed.md, asserting the sentence count stays at 2 under whichever
segmenter is live at the time.

## Reviewer sign-off

Addressed all 5 points from Agent 3R's review:

1. **Wording fix** — Section 3 now says `pipeline.run()` needs "no changes
   **from this spec**," and explicitly credits 00_question_id.md's
   `all_questions.append(q)` change as real but disjoint, rather than
   implying `run()` is untouched by either spec.
2. **02_speed.md dependency** — added an explicit subsection under
   "Sentence counting" in Section 2 spelling out that 3-sentence truncation
   accuracy is contingent on whichever segmenter backs
   `sentence_split.split_sentences` at runtime, that pysbd-on-short-
   interrogative-fragments is untested territory per 02_speed.md's own
   caveats, and that this is a known accepted cross-spec dependency rather
   than a blocker.
3. **Regex gaps** — `_WH_PREFIX_RE` now tolerates `**bold**` markdown
   around the category and two-word "how" categories
   (`how\s+\w+(?:\s+\w+)?`); a new `_LEADING_MARKUP_RE` strips leading
   bullet/dash markup before the prefix match runs. Applied consistently
   in both the standalone helper (Section 2) and the `_parse_questions`
   diff (Section 3).
4. **Checker-prompt prefix stripping** — implemented (previously an open
   question) in new Section 6: `_check_answers` now strips the
   `"<Category>: "` prefix from a local copy of each question's text
   before building the checker prompt, while `Question.text` itself keeps
   the prefix for student-facing rendering. Added to the ownership list in
   Section 5.
5. **Fixture with abbreviation** — added a worked example
   (`"How long: The article, published Jan. 5, doesn't say. Why not?"`)
   showing the sentence-count boundary behavior under spaCy today and the
   specific way a pysbd swap could silently change truncation behavior on
   the same input shape, recommended as a unit test once 02 lands.

### Update: 00_question_id.md superseded

`docs/specs/00_question_id.md` has been marked SUPERSEDED — the feedback
spec was redesigned to key per-sentence on `essay_id` + `sentence_index`
rather than a per-`Question` id, so `Question.id`/`QuestionRecord.id`/
`PipelineResult.all_questions`/`attach_question_ids` no longer exist as a
dependency. This spec's own logic never required any of them (the
normalization step, Wh-prefix regex, 3-sentence cap, and `_parse_questions`
diff were always self-contained), so this was a documentation-only pass:
removed every mention of depending on or being compatible with
`00_question_id.md` (frontmatter Owner note, Section 3's heading/intro and
the `Question(id: int | None = None, ...)` framing, the `all_questions`/
`attach_question_ids` composition discussion, and the "depends on, but
does not own" list in Section 5, which is now simply "depends on no other
spec's changes"). No change to the actual diffs, regexes, or prompt text
in Sections 1-4/6.

### Reconciled with Phase F batching rewrite

`docs/specs/02_speed.md` was completely rewritten (Phase F: single-batch
questioner/checker calls instead of per-sentence parallelization). Agent
1R's integration check found a real gap: this spec's diffs targeted
`_parse_questions` and `_check_answers`, both of which 02's rework
supersedes — `_parse_questions`'s `{"questions": [...]}` contract is
replaced by `_parse_batch_questions`'s index-keyed batch response, and
`_check_answers` is replaced by `_run_batch_checker`/
`build_batch_checker_prompt`. An implementer following 02 alone, without
this update, would have had no hook point left to apply this spec's
Wh-prefix/3-sentence-cap normalization or checker-prompt prefix-stripping
— both would have silently dropped out.

Fixed by relocating both hook points to 02's new function names, with no
change to the normalization logic itself:

1. **Normalization hook (Section 3)** — moved from `_parse_questions`'s
   flat `Question(text=item)` construction to the equivalent per-index
   construction step inside `_parse_batch_questions`'s `range(n)` loop
   (`data.get(str(i))` -> parse each string -> `Question(text=item)`).
   Same one-line substitution
   (`Question(text=item)` -> `Question(text=_normalize_question_text(item))`),
   now applied once per sentence index instead of once per flat list item
   — behaviorally identical, since 02's batch response covers the same
   universe of raw question strings the old per-sentence calls did,
   just gathered in one response instead of `n` responses.
2. **Checker-prompt stripping hook (Section 6)** — moved from
   `_check_answers`'s `[q.text for q in questions]` list construction to
   the equivalent step inside `_run_batch_checker`, where it builds the
   `dict[int, list[str]]` (`checker_text_map`) passed into
   `prompts.build_batch_checker_prompt`. Same substitution
   (`q.text` -> `_CHECKER_STRIP_PREFIX_RE.sub("", q.text, count=1) or q.text`),
   now applied while building that dict's per-index string lists instead
   of a single flat list.
3. **Normalization logic itself is unchanged.** `_normalize_question_text`,
   `_WH_PREFIX_RE`, `_LEADING_MARKUP_RE`, `_DEFAULT_PREFIX`, the
   3-sentence truncation using `sentence_split.split_sentences`, and the
   abbreviation fixture (`"How long: The article, published Jan. 5,
   doesn't say. Why not?"`) all stand as written — only *where* the
   helper gets called changed, not what it does. The pysbd-divergence risk
   already flagged in Section 2 (spaCy vs. pysbd disagreeing on short
   interrogative fragments with abbreviations) is unaffected by 02's
   batching rework — that risk lives in `sentence_split.split_sentences`
   itself, which 02's Phase F rework carries over unchanged from the
   withdrawn thread-pool design (02 §2: "unchanged, unaffected by the
   rework").
4. **Ownership notes (Section 5) and the top-of-file Owner block** now
   name `build_batch_questioner_prompt`, `_parse_batch_questions`, and
   `_run_batch_checker` as the owned hook points, explicitly noting these
   supersede the pre-rework `build_questioner_prompt`/`_parse_questions`/
   `_check_answers` names this spec originally targeted, and that 02 owns
   those functions' actual contracts (batch shape, fail-open granularity,
   timing wiring) — this spec owns only the specific one-line
   substitutions inside them.

No change to Sections 1, 2, or 4, or to the regexes/prompt text/fixture
anywhere in the document — this was a hook-relocation pass only, prompted
by 02's rewrite, not a re-review of this spec's own design.
