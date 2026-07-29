import json
import logging
import re
import time

from huggingface_hub import InferenceClient

import config

logger = logging.getLogger(__name__)

_JSON_BLOCK_RE = re.compile(r"[\{\[].*[\}\]]", re.DOTALL)

_client: InferenceClient | None = None


class LLMError(Exception):
    """Raised when the LLM backend cannot be reached or returns unusable output."""


def _get_client() -> InferenceClient:
    global _client
    if _client is None:
        if not config.HF_TOKEN:
            raise LLMError(
                "HF_TOKEN is not set. Add it to a .env file to use the Hugging Face "
                "Inference API."
            )
        _client = InferenceClient(model=config.MODEL_NAME, token=config.HF_TOKEN, timeout=30)
    return _client


def _extract_json(raw: str):
    match = _JSON_BLOCK_RE.search(raw)
    if not match:
        raise ValueError(f"No JSON object/array found in output: {raw!r}")
    return json.loads(match.group(0))


def _call_model(prompt: str) -> str:
    client = _get_client()
    response = client.chat_completion(
        messages=[{"role": "user", "content": prompt}],
        max_tokens=1024,
    )
    return response.choices[0].message.content


def generate_json(prompt: str, retry_prompt: str | None = None, max_transient_retries: int = 2):
    """Call the model and parse its output as JSON.

    Retries transient backend errors (timeouts, rate limits, cold starts) up to
    `max_transient_retries` times with a short backoff. If the model responds but
    the output isn't valid JSON, retries once with `retry_prompt` (a stricter
    follow-up), then raises LLMError so the caller can skip that round gracefully.
    """
    raw = None
    last_error: Exception | None = None
    for attempt in range(max_transient_retries + 1):
        try:
            raw = _call_model(prompt)
            break
        except Exception as exc:
            last_error = exc
            if attempt < max_transient_retries:
                logger.warning("LLM call failed (attempt %d), retrying: %s", attempt + 1, exc)
                time.sleep(2**attempt)
            continue
    else:
        raise LLMError(f"LLM backend unreachable after retries: {last_error}") from last_error

    try:
        return _extract_json(raw)
    except (ValueError, json.JSONDecodeError) as exc:
        if retry_prompt is None:
            raise LLMError(f"Could not parse JSON from LLM output: {exc}") from exc
        try:
            raw = _call_model(retry_prompt)
            return _extract_json(raw)
        except Exception as retry_exc:
            raise LLMError(f"Could not parse JSON from LLM output after retry: {retry_exc}") from retry_exc
