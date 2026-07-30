from unittest.mock import patch

import pytest

import llm_client
from llm_client import LLMError, generate_json


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(llm_client.time, "sleep", lambda _seconds: None)


def test_valid_json_object():
    with patch.object(llm_client, "_call_model", return_value='{"questions": []}'):
        assert generate_json("prompt") == {"questions": []}


def test_json_embedded_in_extra_text():
    raw = 'Sure, here you go:\n{"answered": true}\nHope that helps!'
    with patch.object(llm_client, "_call_model", return_value=raw):
        assert generate_json("prompt") == {"answered": True}


def test_json_array_output():
    raw = '[{"question": "Who?", "answered": false}]'
    with patch.object(llm_client, "_call_model", return_value=raw):
        assert generate_json("prompt") == [{"question": "Who?", "answered": False}]


def test_malformed_json_retries_with_retry_prompt_and_succeeds():
    responses = iter(["not json at all", '{"ok": true}'])
    with patch.object(llm_client, "_call_model", side_effect=lambda _p: next(responses)):
        assert generate_json("prompt", retry_prompt="please respond with only JSON") == {"ok": True}


def test_malformed_json_no_retry_prompt_raises():
    with patch.object(llm_client, "_call_model", return_value="not json at all"):
        with pytest.raises(LLMError):
            generate_json("prompt")


def test_malformed_json_retry_also_fails_raises():
    with patch.object(llm_client, "_call_model", return_value="still not json"):
        with pytest.raises(LLMError):
            generate_json("prompt", retry_prompt="please respond with only JSON")


def test_transient_error_then_success():
    calls = {"n": 0}

    def side_effect(_prompt):
        calls["n"] += 1
        if calls["n"] < 2:
            raise TimeoutError("cold start")
        return '{"questions": []}'

    with patch.object(llm_client, "_call_model", side_effect=side_effect):
        assert generate_json("prompt") == {"questions": []}
    assert calls["n"] == 2


def test_transient_error_exhausts_retries_raises():
    with patch.object(llm_client, "_call_model", side_effect=TimeoutError("down")):
        with pytest.raises(LLMError):
            generate_json("prompt", max_transient_retries=2)
