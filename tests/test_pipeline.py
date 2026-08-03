from unittest.mock import patch

import prompts
from llm_client import LLMError
from pipeline import run


def _fake_generate_json(questioner_response=None, checker_response=None):
    """Return a side_effect fn that dispatches on which prompt kind is being asked.

    Under the batched design there's at most one questioner call and one
    checker call per `run()` invocation, so each response is a single
    batch-shaped dict, not a per-sentence queue.
    """

    def fake(prompt, retry_prompt=None, **kwargs):
        if retry_prompt == prompts.QUESTIONER_RETRY:
            if questioner_response is None:
                raise AssertionError("unexpected questioner call")
            return questioner_response
        elif retry_prompt == prompts.CHECKER_RETRY:
            if checker_response is None:
                raise AssertionError("unexpected checker call")
            return checker_response
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
    questioner_response = {"0": ["Who is 'here'?"]}
    with patch("llm_client.generate_json", side_effect=_fake_generate_json(questioner_response)):
        result = run(text)
    assert len(result.annotations) == 1
    assert result.annotations[0].sentence_index == 0
    assert [q.text for q in result.annotations[0].questions] == ["Who is 'here'?"]


def test_answered_question_is_dropped():
    text = "The cat sat. It was tired."
    questioner_response = {
        "0": ["Why was it tired?"],
        "1": ["What happened next?"],
    }
    checker_response = {"0": [True]}
    with patch(
        "llm_client.generate_json",
        side_effect=_fake_generate_json(questioner_response, checker_response),
    ):
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
    questioner_response = {
        "0": ["Why was it tired?"],
        "1": ["What happened next?"],
    }
    checker_response = {"0": [False]}
    with patch(
        "llm_client.generate_json",
        side_effect=_fake_generate_json(questioner_response, checker_response),
    ):
        result = run(text)
    sentence_0_annotations = [a for a in result.annotations if a.sentence_index == 0]
    assert len(sentence_0_annotations) == 1
    assert sentence_0_annotations[0].questions[0].text == "Why was it tired?"


def test_checker_prompt_receives_question_text_unchanged():
    text = "The cat sat. It was tired."
    questioner_response = {"0": ["Why was it tired?"], "1": ["What happened next?"]}
    checker_response = {"0": [True]}
    captured = {}

    def fake(prompt, retry_prompt=None, **kwargs):
        if retry_prompt == prompts.QUESTIONER_RETRY:
            return questioner_response
        if retry_prompt == prompts.CHECKER_RETRY:
            captured["prompt"] = prompt
            return checker_response
        raise AssertionError("unexpected retry_prompt")

    with patch("llm_client.generate_json", side_effect=fake):
        run(text)
    assert "Why was it tired?" in captured["prompt"]


def test_questioner_failure_recorded_and_round_skipped():
    text = "The cat sat. It was tired."

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
    questioner_response = {"0": ["Why was it tired?"], "1": ["What X?"]}

    def fake(prompt, retry_prompt=None, **kwargs):
        if retry_prompt == prompts.QUESTIONER_RETRY:
            return questioner_response
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
    questioner_response = {
        "0": [
            "Who is valid one?",
            "",
            {"text": "Not a string"},
            None,
        ]
    }
    with patch("llm_client.generate_json", side_effect=_fake_generate_json(questioner_response)):
        result = run(text)
    assert len(result.annotations) == 1
    assert [q.text for q in result.annotations[0].questions] == ["Who is valid one?"]


def test_missing_sentence_index_in_response_is_failed_round_not_whole_submission():
    text = "The cat sat. It was tired. It slept well."
    # index "1" missing entirely from an otherwise well-formed response
    questioner_response = {"0": ["Why?"], "2": ["What?"]}
    checker_response = {"0": [True]}
    with patch(
        "llm_client.generate_json",
        side_effect=_fake_generate_json(questioner_response, checker_response),
    ):
        result = run(text)
    assert result.failed_rounds == [1]
    # sentence 2 (last sentence) still gets its question, auto-unanswered
    assert any(a.sentence_index == 2 for a in result.annotations)
