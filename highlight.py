from models import Category, PipelineResult

DETAIL = "detail"
REASON = "reason"
MIXED = "mixed"

COLOR_MAP = {
    DETAIL: "#3b82f6",  # blue: missing support/evidence
    REASON: "#f59e0b",  # amber: missing justification
    MIXED: "#a855f7",  # purple: both
}


def _label_for(categories: set[Category]) -> str:
    has_detail = Category.DETAIL in categories
    has_reason = Category.REASON in categories
    if has_detail and has_reason:
        return MIXED
    return DETAIL if has_detail else REASON


def to_highlighted_text(result: PipelineResult) -> list[tuple[str, str | None]]:
    """Build the (text_chunk, label) tuples gr.HighlightedText expects.

    Chunks cover `result.text` contiguously and in order, including the
    unlabeled gaps between sentences (whitespace, etc.), so concatenating all
    chunk texts reproduces the original draft exactly.
    """
    text = result.text
    label_by_sentence: dict[int, str] = {
        annotation.sentence_index: _label_for({q.category for q in annotation.questions})
        for annotation in result.annotations
    }

    chunks: list[tuple[str, str | None]] = []
    cursor = 0
    for sentence in result.sentences:
        if sentence.start_char > cursor:
            chunks.append((text[cursor:sentence.start_char], None))
        chunks.append((sentence.text, label_by_sentence.get(sentence.index)))
        cursor = sentence.end_char
    if cursor < len(text):
        chunks.append((text[cursor:], None))
    return chunks


def chunk_sentence_indices(result: PipelineResult) -> list[int | None]:
    """Parallel list to `to_highlighted_text`'s chunks: the sentence index each
    chunk belongs to, or None for the unlabeled gaps between sentences."""
    indices: list[int | None] = []
    cursor = 0
    for sentence in result.sentences:
        if sentence.start_char > cursor:
            indices.append(None)
        indices.append(sentence.index)
        cursor = sentence.end_char
    if cursor < len(result.text):
        indices.append(None)
    return indices


def annotated_draft_text(result: PipelineResult) -> str:
    """Build the downloadable draft: original text with each unanswered
    question inserted inline as a bracketed note right after its sentence."""
    text = result.text
    annotation_by_sentence = {a.sentence_index: a for a in result.annotations}

    pieces: list[str] = []
    cursor = 0
    for sentence in result.sentences:
        pieces.append(text[cursor:sentence.end_char])
        cursor = sentence.end_char
        annotation = annotation_by_sentence.get(sentence.index)
        if annotation:
            for question in annotation.questions:
                pieces.append(f" [{question.category.value.upper()}: {question.text}]")
    pieces.append(text[cursor:])
    return "".join(pieces)
