import json
import logging
import re
import time
from typing import Callable

import llm_providers
from errors import LLMError  # re-exported: callers use llm_client.LLMError

__all__ = ["LLMError", "generate_json"]

logger = logging.getLogger(__name__)

_JSON_BLOCK_RE = re.compile(r"[\{\[].*[\}\]]", re.DOTALL)


def _extract_json(raw: str):
    match = _JSON_BLOCK_RE.search(raw)
    if not match:
        raise ValueError(f"No JSON object/array found in output: {raw!r}")
    return json.loads(match.group(0))


def _call_model(prompt: str) -> llm_providers.LLMResponse:
    """Call the configured provider and return its normalized response.

    The response carries the model text plus optional token counts so callers
    can also track token usage. This is the seam the provider adapters plug
    into (see `llm_providers.py`).
    """
    return llm_providers.get_provider().complete(prompt)


def generate_json(
    prompt: str,
    retry_prompt: str | None = None,
    max_transient_retries: int = 2,
    on_attempt: Callable[[], None] | None = None,
    on_result: Callable[[int | None, int | None], None] | None = None,
):
    """Call the model and parse its output as JSON.

    Retries transient backend errors (timeouts, rate limits, cold starts) up to
    `max_transient_retries` times with a short backoff. If the model responds but
    the output isn't valid JSON, retries once with `retry_prompt` (a stricter
    follow-up), then raises LLMError so the caller can skip that round gracefully.

    `on_attempt`, if given, is invoked once per retry actually taken (transient
    backoff retry or JSON-parse retry), never on a clean first-try success.
    `on_result`, if given, is invoked once on success with
    `(prompt_tokens, completion_tokens)` from the provider response that
    ultimately succeeded, or `(None, None)` if the backend didn't report them.
    """
    raw = None
    response: llm_providers.LLMResponse | None = None
    last_error: Exception | None = None
    for attempt in range(max_transient_retries + 1):
        try:
            response = _call_model(prompt)
            raw = response.text
            break
        except LLMError:
            # A configuration error (unknown provider, missing SDK / API key /
            # model) — deterministic, not transient. Surface it immediately so
            # the caller can fail open without burning the backoff budget.
            raise
        except Exception as exc:
            last_error = exc
            if attempt < max_transient_retries:
                if on_attempt is not None:
                    on_attempt()
                # exc_info goes to server logs only; keep the message free of
                # raw SDK/URL strings that could carry credentials.
                logger.warning(
                    "LLM call failed (attempt %d), retrying", attempt + 1, exc_info=True
                )
                time.sleep(2**attempt)
            continue
    else:
        raise LLMError(
            f"LLM backend unreachable after retries ({type(last_error).__name__})"
        ) from last_error

    try:
        data = _extract_json(raw)
    except (ValueError, json.JSONDecodeError) as exc:
        if retry_prompt is None:
            raise LLMError(f"Could not parse JSON from LLM output: {exc}") from exc
        try:
            if on_attempt is not None:
                on_attempt()
            response = _call_model(retry_prompt)
            raw = response.text
            data = _extract_json(raw)
        except Exception as retry_exc:
            raise LLMError(
                "Could not get parseable JSON from the LLM after a retry "
                f"({type(retry_exc).__name__})"
            ) from retry_exc

    if on_result is not None:
        # `response` is always set here: the loop only breaks after assigning it.
        prompt_tokens = response.prompt_tokens
        completion_tokens = response.completion_tokens
        on_result(prompt_tokens, completion_tokens)

    return data
