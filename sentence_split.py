import pysbd

from models import Sentence

_segmenter = None


def _get_segmenter():
    global _segmenter
    if _segmenter is None:
        _segmenter = pysbd.Segmenter(language="en", clean=False, char_span=True)
    return _segmenter


def split_sentences(text: str) -> list[Sentence]:
    """
    Splits the text into a list of sentences
    """
    if not text:
        return []

    spans = _get_segmenter().segment(text)

    sentences = []
    for i, span in enumerate(spans):
        stripped = span.sent.rstrip()
        sentences.append(
            Sentence(
                index=i,
                text=stripped,
                start_char=span.start,
                end_char=span.start + len(stripped),
            )
        )
    return sentences
