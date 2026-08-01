from pipeline import _normalize_question_text


def test_already_compliant_text_passes_through():
    assert _normalize_question_text("Who: Who says that?") == "Who: Who says that?"


def test_missing_prefix_falls_back_to_what():
    assert _normalize_question_text("Does it rain a lot?") == "What: Does it rain a lot?"


def test_lowercase_prefix_is_recased():
    assert _normalize_question_text("who: who says that?") == "Who: who says that?"


def test_bullet_and_bold_markup_stripped_before_prefix_match():
    assert _normalize_question_text("- **Who:** Who says that?") == "Who: Who says that?"


def test_two_word_how_category_recognized():
    assert _normalize_question_text("How much longer: will it take?") == "How much longer: will it take?"


def test_over_length_question_truncated_to_three_sentences():
    raw = "Why: One. Two. Three. Four."
    assert _normalize_question_text(raw) == "Why: One. Two. Three."


def test_abbreviation_does_not_cause_premature_truncation():
    raw = "How long: The article, published Jan. 5, doesn't say. Why not?"
    assert _normalize_question_text(raw) == raw


def test_never_crashes_on_prefix_only_input():
    result = _normalize_question_text("Who:")
    assert result.startswith("Who:")
