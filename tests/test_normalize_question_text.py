from pipeline import _normalize_question_text


def test_already_compliant_one_sentence_question_passes_through():
    assert _normalize_question_text("Who says that?") == "Who says that?"


def test_multi_sentence_input_truncated_to_first_sentence():
    raw = "What new policy would the school board consider? It matters a lot."
    assert _normalize_question_text(raw) == "What new policy would the school board consider?"


def test_bullet_and_bold_markup_stripped_before_validation():
    assert _normalize_question_text("- **Who says that?**") == "Who says that?"


def test_never_crashes_on_empty_input():
    assert _normalize_question_text("") == ""


def test_never_crashes_on_whitespace_only_input():
    assert _normalize_question_text("   ") == ""
