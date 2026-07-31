from unittest.mock import patch

import prompts
from llm_client import LLMError
from pipeline import run


def _questioner_response(*texts):
    return {"questions": list(texts)}


def _checker_response(*answered_flags):
    return [{"question": f"q{i}", "answered": flag} for i, flag in enumerate(answered_flags)]


def _fake_generate_json(responses):
    """Return a side_effect fn that dispatches on which prompt kind is being asked."""

    def fake(prompt, retry_prompt=None, **kwargs):
        if retry_prompt == prompts.QUESTIONER_RETRY:
            return responses["questioner"].pop(0)
        elif retry_prompt == prompts.CHECKER_RETRY:
            return responses["checker"].pop(0)
        raise AssertionError("unexpected retry_prompt")

    return fake


def test_empty_draft_no_llm_calls():
    with patch("llm_client.generate_json") as mock_generate:
        result = run("")
    mock_generate.assert_not_called()
    assert result.sentences == []
    assert result.annotations == []


def test_last_sentence_auto_unanswered_no_checker_call():
    text = "Only one sentence here."
    responses = {"questioner": [_questioner_response("Who is 'here'?")], "checker": []}
    with patch("llm_client.generate_json", side_effect=_fake_generate_json(responses)):
        result = run(text)
    assert len(result.annotations) == 1
    assert result.annotations[0].sentence_index == 0
    assert [q.text for q in result.annotations[0].questions] == ["Who is 'here'?"]


def test_answered_question_is_dropped():
    text = "The cat sat. It was tired."
    responses = {
        "questioner": [
            _questioner_response("Why was it tired?"),
            _questioner_response("What happened next?"),
        ],
        "checker": [_checker_response(True)],
    }
    with patch("llm_client.generate_json", side_effect=_fake_generate_json(responses)):
        result = run(text)
    # sentence 0's question was answered -> no annotation for it
    assert all(a.sentence_index != 0 for a in result.annotations)
    # sentence 1 is the last sentence -> auto-unanswered
    assert any(a.sentence_index == 1 for a in result.annotations)
    # both generated questions are logged, in order, with correct shown flags
    assert [(r.text, r.shown) for r in result.question_log] == [
        ("Why was it tired?", False),
        ("What happened next?", True),
    ]


def test_unanswered_question_becomes_annotation():
    text = "The cat sat. It was tired."
    responses = {
        "questioner": [
            _questioner_response("Why was it tired?"),
            _questioner_response("What happened next?"),
        ],
        "checker": [_checker_response(False)],
    }
    with patch("llm_client.generate_json", side_effect=_fake_generate_json(responses)):
        result = run(text)
    sentence_0_annotations = [a for a in result.annotations if a.sentence_index == 0]
    assert len(sentence_0_annotations) == 1
    assert sentence_0_annotations[0].questions[0].text == "Why was it tired?"


def test_questioner_failure_recorded_and_round_skipped():
    text = "The cat sat. It was tired."
    responses = {"questioner": [], "checker": []}

    def fake(prompt, retry_prompt=None, **kwargs):
        if retry_prompt == prompts.QUESTIONER_RETRY:
            raise LLMError("backend unreachable")
        raise AssertionError("checker should not be called")

    with patch("llm_client.generate_json", side_effect=fake):
        result = run(text)
    assert result.failed_rounds == [0, 1]
    assert result.annotations == []


def test_checker_failure_fails_open_to_unanswered():
    text = "The cat sat. It was tired."
    responses = {"questioner": [_questioner_response("Why was it tired?"), _questioner_response("X?")]}

    def fake(prompt, retry_prompt=None, **kwargs):
        if retry_prompt == prompts.QUESTIONER_RETRY:
            return responses["questioner"].pop(0)
        if retry_prompt == prompts.CHECKER_RETRY:
            raise LLMError("backend unreachable")
        raise AssertionError("unexpected retry_prompt")

    with patch("llm_client.generate_json", side_effect=fake):
        result = run(text)
    sentence_0_annotations = [a for a in result.annotations if a.sentence_index == 0]
    assert len(sentence_0_annotations) == 1
    assert sentence_0_annotations[0].questions[0].text == "Why was it tired?"


def test_malformed_question_entries_are_skipped():
    text = "Only one sentence here."
    responses = {
        "questioner": [
            {
                "questions": [
                    "Valid one?",
                    "",
                    {"text": "Not a string"},
                    None,
                ]
            }
        ],
        "checker": [],
    }
    with patch("llm_client.generate_json", side_effect=_fake_generate_json(responses)):
        result = run(text)
    assert len(result.annotations) == 1
    assert [q.text for q in result.annotations[0].questions] == ["Valid one?"]
