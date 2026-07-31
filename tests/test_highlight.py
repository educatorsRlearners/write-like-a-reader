from highlight import SENTENCE, annotated_draft_text, chunk_sentence_indices, to_highlighted_text
from models import Annotation, PipelineResult, Question
from sentence_split import split_sentences


def _make_result(text: str, annotations: list[Annotation]) -> PipelineResult:
    return PipelineResult(text=text, sentences=split_sentences(text), annotations=annotations)


def test_no_annotations_round_trips_and_sentences_all_labeled():
    text = "The cat sat. It was tired. It slept well."
    result = _make_result(text, [])
    chunks = to_highlighted_text(result)
    assert "".join(chunk_text for chunk_text, _ in chunks) == text
    labels = {c: label for c, label in chunks if label is not None}
    assert all(sentence.text in labels for sentence in result.sentences)
    assert all(label == SENTENCE for label in labels.values())


def test_annotated_sentence_gets_same_label_as_unannotated():
    text = "The cat sat. It was tired."
    sentences = split_sentences(text)
    annotation = Annotation(
        sentence_index=0,
        start_char=sentences[0].start_char,
        end_char=sentences[0].end_char,
        questions=[Question(text="What cat?")],
    )
    result = _make_result(text, [annotation])
    chunks = to_highlighted_text(result)
    assert "".join(c for c, _ in chunks) == text
    labels = {c: label for c, label in chunks if label is not None}
    assert labels[sentences[0].text] == SENTENCE
    assert labels[sentences[1].text] == SENTENCE


def test_annotated_draft_text_inserts_notes_after_correct_sentence():
    text = "The cat sat. It was tired."
    sentences = split_sentences(text)
    annotation = Annotation(
        sentence_index=0,
        start_char=sentences[0].start_char,
        end_char=sentences[0].end_char,
        questions=[Question(text="What cat?")],
    )
    result = _make_result(text, [annotation])
    annotated = annotated_draft_text(result)
    assert annotated == "The cat sat. [What cat?] It was tired."


def test_annotated_draft_text_no_annotations_unchanged():
    text = "The cat sat. It was tired."
    result = _make_result(text, [])
    assert annotated_draft_text(result) == text


def test_chunk_sentence_indices_parallels_chunks():
    text = "The cat sat. It was tired. It slept well."
    result = _make_result(text, [])
    chunks = to_highlighted_text(result)
    indices = chunk_sentence_indices(result)
    assert len(chunks) == len(indices)
    for (chunk_text, _label), sentence_index in zip(chunks, indices):
        if sentence_index is not None:
            assert chunk_text == result.sentences[sentence_index].text
