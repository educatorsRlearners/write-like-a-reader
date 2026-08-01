import logging
import re
import time

import llm_client
import prompts
import sentence_split
import storage
from models import Annotation, PipelineResult, Question, QuestionRecord
from sentence_split import split_sentences

logger = logging.getLogger(__name__)

# Strip a leading bullet/markdown marker ("- ", "* ", "**") before matching
# the category, since the questioner may echo bullet-list formatting (e.g.
# "- Who: ..." or "**Who:** ...") even though the JSON response instruction
# asks for a bare array of strings.
_LEADING_MARKUP_RE = re.compile(r"^[\-\*\s]+")
# `how\s+\w+(?:\s+\w+)?` covers both one-word ("how long", "how often") and
# two-word ("how much longer", "how many times") "how" categories.
_WH_PREFIX_RE = re.compile(
    r"^\**(who|what|when|where|why|how\s+\w+(?:\s+\w+)?)\**\s*:\**\s*", re.IGNORECASE
)
_DEFAULT_PREFIX = "What"
# Reused as-is to strip a question's Wh-prefix before it's sent to the
# checker LLM -- the student-facing `Question.text` keeps its prefix.
_CHECKER_STRIP_PREFIX_RE = _WH_PREFIX_RE


def _normalize_question_text(raw: str) -> str:
    """Enforce the Wh-prefix and 3-sentence constraints on one question string.

    Returns the normalized text; never returns an empty string for
    non-empty input (falls back to a `What:` prefix rather than dropping
    the question).
    """
    text = _LEADING_MARKUP_RE.sub("", raw.strip()).strip()

    match = _WH_PREFIX_RE.match(text)
    if match:
        prefix = match.group(1)
        body = text[match.end() :].strip()
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


def _parse_batch_questions(data, n: int) -> tuple[dict[int, list[Question]], set[int]]:
    """Parse a batch questioner response, index-keyed by sentence.

    A sentence index that's missing, not a list, or absent from a
    non-dict `data` gets an empty question list and is recorded in
    `failed_indices` -- this is per-sentence fail-open, applied against one
    shared response instead of per-call.
    """
    questions_by_index: dict[int, list[Question]] = {}
    failed_indices: set[int] = set()
    is_dict = isinstance(data, dict)
    for i in range(n):
        raw_list = data.get(str(i)) if is_dict else None
        if not isinstance(raw_list, list):
            questions_by_index[i] = []
            failed_indices.add(i)
            continue
        parsed = []
        for item in raw_list:
            if isinstance(item, str) and item.strip():
                parsed.append(Question(text=_normalize_question_text(item)))
        questions_by_index[i] = parsed
    return questions_by_index, failed_indices


def _parse_batch_verdicts(
    data, question_map: dict[int, list[Question]]
) -> dict[int, list[Question]]:
    """Return, per sentence index in `question_map`, the subset NOT answered.

    `question_map` here is already filtered to indices actually sent to the
    checker (has a next sentence, has questions). If `data` is missing or
    malformed for a given index, that whole index's questions are treated
    as unanswered (fail open), independent of any other index.
    """
    is_dict = isinstance(data, dict)
    unanswered_map: dict[int, list[Question]] = {}
    for i, questions in question_map.items():
        verdicts = data.get(str(i)) if is_dict else None
        if not isinstance(verdicts, list):
            unanswered_map[i] = list(questions)
            continue
        unanswered = []
        for j, question in enumerate(questions):
            verdict = verdicts[j] if j < len(verdicts) else None
            if verdict is True:
                continue
            unanswered.append(question)
        unanswered_map[i] = unanswered
    return unanswered_map


def _record_call(
    essay_id,
    call_type,
    sentence_count,
    status,
    retries,
    duration_ms,
    prompt_tokens,
    completion_tokens,
    error_message,
):
    if essay_id is None:
        return
    try:
        storage.save_llm_call(
            essay_id,
            None,  # sentence_index -- always NULL for a batched call
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


def _timed_call(essay_id, call_type: str, sentence_count: int, prompt: str, retry_prompt: str):
    """Shared by both the questioner and checker call sites. `call_type`
    and `sentence_count` are passed in by the caller -- never hardcoded
    here, so a checker failure can never get mis-logged as a questioner row.
    """
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
            prompt, retry_prompt=retry_prompt, on_attempt=_bump, on_result=_capture
        )
    except llm_client.LLMError as exc:
        duration_ms = int((time.perf_counter() - start) * 1000)
        _record_call(
            essay_id, call_type, sentence_count, "failed", retries, duration_ms,
            prompt_tokens, completion_tokens, str(exc),
        )
        raise
    duration_ms = int((time.perf_counter() - start) * 1000)
    _record_call(
        essay_id, call_type, sentence_count, "success", retries, duration_ms,
        prompt_tokens, completion_tokens, None,
    )
    return data


def _run_batch_questioner(essay_id, sentences) -> tuple[dict[int, list[Question]], set[int]]:
    n = len(sentences)
    prompt = prompts.build_batch_questioner_prompt([s.text for s in sentences])
    try:
        data = _timed_call(essay_id, "questioner", n, prompt, prompts.QUESTIONER_RETRY)
    except llm_client.LLMError:
        return {}, set(range(n))
    return _parse_batch_questions(data, n)


def _run_batch_checker(
    essay_id, question_map: dict[int, list[Question]], sentences, n: int
) -> dict[int, list[Question]]:
    """Return, per sentence index < n - 1, the subset of that index's
    questions NOT answered by the next sentence. Fails open at both the
    whole-call level (backend unreachable / unparseable) and the per-index
    level (a specific sentence's data missing/malformed in an otherwise
    valid response) -- see `_parse_batch_verdicts`.
    """
    checkable = {i: qs for i, qs in question_map.items() if i < n - 1 and qs}
    if not checkable:
        return {}

    checker_text_map = {
        i: [_CHECKER_STRIP_PREFIX_RE.sub("", q.text, count=1) or q.text for q in qs]
        for i, qs in checkable.items()
    }
    prompt = prompts.build_batch_checker_prompt(checker_text_map, [s.text for s in sentences])
    try:
        data = _timed_call(essay_id, "checker", len(checkable), prompt, prompts.CHECKER_RETRY)
    except llm_client.LLMError:
        return {i: list(qs) for i, qs in checkable.items()}
    return _parse_batch_verdicts(data, checkable)


def run(text: str, essay_id: int | None = None, on_progress=None) -> PipelineResult:
    """Run the batched pipeline: one questioner call, one checker call.

    `on_progress`, if given, is called as `on_progress(step, 2)` before each
    of the two batch calls.
    """
    sentences = split_sentences(text)
    n = len(sentences)
    result = PipelineResult(text=text, sentences=sentences, essay_id=essay_id)
    if n == 0:
        return result

    if on_progress is not None:
        on_progress(0, 2)

    question_map, failed_indices = _run_batch_questioner(essay_id, sentences)
    result.failed_rounds.extend(sorted(failed_indices))

    if on_progress is not None:
        on_progress(1, 2)

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
            result.annotations.append(
                Annotation(
                    sentence_index=sentences[i].index,
                    start_char=sentences[i].start_char,
                    end_char=sentences[i].end_char,
                    questions=unanswered,
                )
            )

    return result
