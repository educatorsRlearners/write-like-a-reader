from dataclasses import dataclass, field
from enum import Enum


@dataclass(frozen=True)
class Sentence:
    index: int
    text: str
    start_char: int
    end_char: int


class Category(str, Enum):
    DETAIL = "detail"
    REASON = "reason"


@dataclass(frozen=True)
class Question:
    text: str
    category: Category


@dataclass(frozen=True)
class Annotation:
    sentence_index: int
    start_char: int
    end_char: int
    questions: list[Question]


@dataclass
class PipelineResult:
    text: str
    sentences: list[Sentence]
    annotations: list[Annotation] = field(default_factory=list)
    failed_rounds: list[int] = field(default_factory=list)
