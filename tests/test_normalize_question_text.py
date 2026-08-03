from pipeline import _normalize_question_text


def test_already_compliant_one_sentence_question_passes_through():
    assert _normalize_question_text("Who says that?") == "Who says that?"


def test_multi_sentence_input_truncated_to_first_sentence():
    raw = "What new policy would the school board consider? It matters a lot."
    assert _normalize_question_text(raw) == "What new policy would the school board consider?"


def test_non_wh_first_word_passes_through_unchanged(caplog):
    with caplog.at_level("WARNING"):
        result = _normalize_question_text("Does it rain a lot?")
    assert result == "Does it rain a lot?"
    assert "Wh-word" in caplog.text


def test_bullet_and_bold_markup_stripped_before_validation():
    assert _normalize_question_text("- **Who says that?**") == "Who says that?"


def test_lowercase_wh_word_is_compliant_and_left_untouched():
    assert _normalize_question_text("what happened next?") == "what happened next?"


def test_never_crashes_on_empty_input():
    assert _normalize_question_text("") == ""


def test_never_crashes_on_whitespace_only_input():
    assert _normalize_question_text("   ") == ""
