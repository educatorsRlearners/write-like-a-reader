import llm_client
import prompts
from models import Annotation, PipelineResult, Question, QuestionRecord
from sentence_split import split_sentences


def _parse_questions(data) -> list[Question]:
    if not isinstance(data, dict):
        return []
    questions = []
    for item in data.get("questions", []):
        if isinstance(item, str) and item.strip():
            questions.append(Question(text=item))
    return questions


def _check_answers(questions: list[Question], next_sentence: str) -> list[Question]:
    """Return the subset of `questions` NOT answered by `next_sentence`.

    Fails open: any question the checker can't confirm as answered (checker call
    fails, response is malformed, or a specific question is missing from the
    response) is treated as unanswered rather than silently dropped.
    """
    prompt = prompts.build_checker_prompt([q.text for q in questions], next_sentence)
    try:
        data = llm_client.generate_json(prompt, retry_prompt=prompts.CHECKER_RETRY)
    except llm_client.LLMError:
        return questions

    if not isinstance(data, list):
        return questions

    unanswered = []
    for i, question in enumerate(questions):
        verdict = data[i] if i < len(data) else None
        if isinstance(verdict, dict) and verdict.get("answered") is True:
            continue
        unanswered.append(question)
    return unanswered


def run(text: str, on_progress=None) -> PipelineResult:
    """Run the sentence-by-sentence pipeline.

    `on_progress`, if given, is called as `on_progress(i, n)` before processing
    each sentence `i` of `n` total sentences.
    """
    sentences = split_sentences(text)
    result = PipelineResult(text=text, sentences=sentences)
    n = len(sentences)

    for i, sentence in enumerate(sentences):
        if on_progress is not None:
            on_progress(i, n)
        prompt = prompts.build_questioner_prompt([s.text for s in sentences[: i + 1]], i)
        try:
            data = llm_client.generate_json(prompt, retry_prompt=prompts.QUESTIONER_RETRY)
        except llm_client.LLMError:
            result.failed_rounds.append(i)
            continue

        questions = _parse_questions(data)
        if not questions:
            continue

        if i == n - 1:
            unanswered = questions
        else:
            unanswered = _check_answers(questions, sentences[i + 1].text)

        shown_ids = {id(q) for q in unanswered}
        for q in questions:
            result.question_log.append(QuestionRecord(text=q.text, shown=id(q) in shown_ids))

        if unanswered:
            result.annotations.append(
                Annotation(
                    sentence_index=sentence.index,
                    start_char=sentence.start_char,
                    end_char=sentence.end_char,
                    questions=unanswered,
                )
            )

    return result
