from dataclasses import dataclass, field


@dataclass(frozen=True)
class Sentence:
    index: int
    text: str
    start_char: int
    end_char: int


@dataclass(frozen=True)
class Question:
    text: str


@dataclass(frozen=True)
class Annotation:
    sentence_index: int
    start_char: int
    end_char: int
    questions: list[Question]


@dataclass(frozen=True)
class QuestionRecord:
    text: str
    shown: bool


@dataclass
class PipelineResult:
    text: str
    sentences: list[Sentence]
    annotations: list[Annotation] = field(default_factory=list)
    failed_rounds: list[int] = field(default_factory=list)
    question_log: list[QuestionRecord] = field(default_factory=list)
    essay_id: int | None = None
