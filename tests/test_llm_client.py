from unittest.mock import patch

import pytest

import llm_client
from llm_client import LLMError, generate_json


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(llm_client.time, "sleep", lambda _seconds: None)


def _response(content, prompt_eval_count=None, eval_count=None):
    resp = {"message": {"content": content}}
    if prompt_eval_count is not None:
        resp["prompt_eval_count"] = prompt_eval_count
    if eval_count is not None:
        resp["eval_count"] = eval_count
    return resp


def test_valid_json_object():
    with patch.object(llm_client, "_call_model", return_value=_response('{"questions": []}')):
        assert generate_json("prompt") == {"questions": []}


def test_json_embedded_in_extra_text():
    raw = 'Sure, here you go:\n{"answered": true}\nHope that helps!'
    with patch.object(llm_client, "_call_model", return_value=_response(raw)):
        assert generate_json("prompt") == {"answered": True}


def test_json_array_output():
    raw = '[{"question": "Who?", "answered": false}]'
    with patch.object(llm_client, "_call_model", return_value=_response(raw)):
        assert generate_json("prompt") == [{"question": "Who?", "answered": False}]


def test_malformed_json_retries_with_retry_prompt_and_succeeds():
    responses = iter([_response("not json at all"), _response('{"ok": true}')])
    with patch.object(llm_client, "_call_model", side_effect=lambda _p: next(responses)):
        assert generate_json("prompt", retry_prompt="please respond with only JSON") == {"ok": True}


def test_malformed_json_no_retry_prompt_raises():
    with patch.object(llm_client, "_call_model", return_value=_response("not json at all")):
        with pytest.raises(LLMError):
            generate_json("prompt")


def test_malformed_json_retry_also_fails_raises():
    with patch.object(llm_client, "_call_model", return_value=_response("still not json")):
        with pytest.raises(LLMError):
            generate_json("prompt", retry_prompt="please respond with only JSON")


def test_transient_error_then_success():
    calls = {"n": 0}

    def side_effect(_prompt):
        calls["n"] += 1
        if calls["n"] < 2:
            raise TimeoutError("cold start")
        return _response('{"questions": []}')

    with patch.object(llm_client, "_call_model", side_effect=side_effect):
        assert generate_json("prompt") == {"questions": []}
    assert calls["n"] == 2


def test_transient_error_exhausts_retries_raises():
    with patch.object(llm_client, "_call_model", side_effect=TimeoutError("down")):
        with pytest.raises(LLMError):
            generate_json("prompt", max_transient_retries=2)


def test_on_attempt_called_once_per_retry_not_on_clean_success():
    attempts = []
    with patch.object(llm_client, "_call_model", return_value=_response('{"ok": true}')):
        generate_json("prompt", on_attempt=lambda: attempts.append(1))
    assert attempts == []


def test_on_attempt_called_for_transient_retry():
    attempts = []
    calls = {"n": 0}

    def side_effect(_prompt):
        calls["n"] += 1
        if calls["n"] < 2:
            raise TimeoutError("cold start")
        return _response('{"ok": true}')

    with patch.object(llm_client, "_call_model", side_effect=side_effect):
        generate_json("prompt", on_attempt=lambda: attempts.append(1))
    assert attempts == [1]


def test_on_attempt_called_for_json_retry():
    attempts = []
    responses = iter([_response("not json"), _response('{"ok": true}')])
    with patch.object(llm_client, "_call_model", side_effect=lambda _p: next(responses)):
        generate_json(
            "prompt", retry_prompt="please respond with only JSON",
            on_attempt=lambda: attempts.append(1),
        )
    assert attempts == [1]


def test_on_result_receives_token_counts():
    captured = []
    with patch.object(
        llm_client, "_call_model",
        return_value=_response('{"ok": true}', prompt_eval_count=42, eval_count=7),
    ):
        generate_json("prompt", on_result=lambda pt, ct: captured.append((pt, ct)))
    assert captured == [(42, 7)]


def test_on_result_defaults_to_none_when_backend_omits_counts():
    captured = []
    with patch.object(llm_client, "_call_model", return_value=_response('{"ok": true}')):
        generate_json("prompt", on_result=lambda pt, ct: captured.append((pt, ct)))
    assert captured == [(None, None)]
