import json
import logging
import re
import time
from typing import Callable

import ollama

import config

logger = logging.getLogger(__name__)

_JSON_BLOCK_RE = re.compile(r"[\{\[].*[\}\]]", re.DOTALL)

_client: ollama.Client | None = None


class LLMError(Exception):
    """Raised when the LLM backend cannot be reached or returns unusable output."""


def _get_client() -> ollama.Client:
    global _client
    if _client is None:
        _client = ollama.Client(host=config.OLLAMA_HOST, timeout=config.OLLAMA_TIMEOUT)
    return _client


def _extract_json(raw: str):
    match = _JSON_BLOCK_RE.search(raw)
    if not match:
        raise ValueError(f"No JSON object/array found in output: {raw!r}")
    return json.loads(match.group(0))


def _call_model(prompt: str) -> dict:
    """Call the model and return the full Ollama chat response.

    Returns the whole response (not just the message content) so callers can
    also read `prompt_eval_count`/`eval_count` for token-usage tracking.
    """
    client = _get_client()
    return client.chat(
        model=config.OLLAMA_MODEL,
        messages=[{"role": "user", "content": prompt}],
        options={"num_predict": 2048, "num_ctx": 8192},
    )


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
    `(prompt_tokens, completion_tokens)` -- Ollama's `prompt_eval_count`/
    `eval_count` from the response that ultimately succeeded, or `(None, None)`
    if the backend didn't report them.
    """
    raw = None
    response: dict | None = None
    last_error: Exception | None = None
    for attempt in range(max_transient_retries + 1):
        try:
            response = _call_model(prompt)
            raw = response["message"]["content"]
            break
        except Exception as exc:
            last_error = exc
            if attempt < max_transient_retries:
                if on_attempt is not None:
                    on_attempt()
                logger.warning("LLM call failed (attempt %d), retrying: %s", attempt + 1, exc)
                time.sleep(2**attempt)
            continue
    else:
        raise LLMError(f"LLM backend unreachable after retries: {last_error}") from last_error

    try:
        data = _extract_json(raw)
    except (ValueError, json.JSONDecodeError) as exc:
        if retry_prompt is None:
            raise LLMError(f"Could not parse JSON from LLM output: {exc}") from exc
        try:
            if on_attempt is not None:
                on_attempt()
            response = _call_model(retry_prompt)
            raw = response["message"]["content"]
            data = _extract_json(raw)
        except Exception as retry_exc:
            raise LLMError(f"Could not parse JSON from LLM output after retry: {retry_exc}") from retry_exc

    if on_result is not None:
        prompt_tokens = response.get("prompt_eval_count") if response else None
        completion_tokens = response.get("eval_count") if response else None
        on_result(prompt_tokens, completion_tokens)

    return data
