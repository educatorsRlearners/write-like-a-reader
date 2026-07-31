from models import PipelineResult

SENTENCE = "sentence"

# Every sentence gets this single label so gr.HighlightedText keeps each one
# individually clickable (Gradio only fires select events on labeled tokens).
# The literal string "transparent" is the one color value Gradio's frontend
# treats as truly transparent (see gradio's correct_color_map JS helper) --
# anything else (e.g. an rgba() string) gets parsed as an opaque color and
# falls back to a visible default, defeating the point.
COLOR_MAP = {SENTENCE: "transparent"}


def to_highlighted_text(result: PipelineResult) -> list[tuple[str, str | None]]:
    """Build the (text_chunk, label) tuples gr.HighlightedText expects.

    Chunks cover `result.text` contiguously and in order, including the
    unlabeled gaps between sentences (whitespace, etc.), so concatenating all
    chunk texts reproduces the original draft exactly. Every sentence gets the
    same `SENTENCE` label (rendered transparent via `COLOR_MAP`) so the whole
    draft stays clickable without singling any sentence out visually.
    """
    text = result.text
    chunks: list[tuple[str, str | None]] = []
    cursor = 0
    for sentence in result.sentences:
        if sentence.start_char > cursor:
            chunks.append((text[cursor : sentence.start_char], None))
        chunks.append((sentence.text, SENTENCE))
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
        pieces.append(text[cursor : sentence.end_char])
        cursor = sentence.end_char
        annotation = annotation_by_sentence.get(sentence.index)
        if annotation:
            for question in annotation.questions:
                pieces.append(f" [{question.text}]")
    pieces.append(text[cursor:])
    return "".join(pieces)
