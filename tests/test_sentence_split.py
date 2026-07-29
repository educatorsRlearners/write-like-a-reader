from sentence_split import split_sentences


def test_single_sentence():
    text = "The cat sat on the mat."
    sentences = split_sentences(text)
    assert len(sentences) == 1
    assert sentences[0].text == text


def test_multiple_sentences_offsets_reconstruct_text():
    text = "The cat sat on the mat. Then it slept. Why did it sleep?"
    sentences = split_sentences(text)
    assert len(sentences) == 3
    for i, sentence in enumerate(sentences):
        assert sentence.index == i
        assert text[sentence.start_char:sentence.end_char] == sentence.text


def test_abbreviation_does_not_split_sentence():
    text = "Dr. Smith arrived early. She examined the patient."
    sentences = split_sentences(text)
    assert len(sentences) == 2
    assert sentences[0].text == "Dr. Smith arrived early."
    assert sentences[1].text == "She examined the patient."


def test_quotes_preserved_in_offsets():
    text = 'She said, "This is great." He agreed.'
    sentences = split_sentences(text)
    assert len(sentences) == 2
    for sentence in sentences:
        assert text[sentence.start_char:sentence.end_char] == sentence.text


def test_empty_text():
    assert split_sentences("") == []
