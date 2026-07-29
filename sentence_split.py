import spacy

from models import Sentence

_nlp = None


def _get_nlp():
    global _nlp
    if _nlp is None:
        _nlp = spacy.load("en_core_web_sm", exclude=["ner", "lemmatizer"])
    return _nlp


def split_sentences(text: str) -> list[Sentence]:
    doc = _get_nlp()(text)
    return [
        Sentence(
            index=i,
            text=span.text,
            start_char=span.start_char,
            end_char=span.end_char,
        )
        for i, span in enumerate(doc.sents)
    ]
