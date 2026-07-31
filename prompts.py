QUESTIONER_RETRY = (
    "Your previous response was not valid JSON. Respond with ONLY a JSON object "
    'of the form {"questions": ["...", "..."]}, no other text.'
)

CHECKER_RETRY = (
    "Your previous response was not valid JSON. Respond with ONLY a JSON array "
    'of the form [{"question": "...", "answered": true|false}], no other text.'
)


def build_questioner_prompt(sentences_so_far: list[str], current_index: int) -> str:
    read_so_far = "\n".join(
        f'{"-> " if i == current_index else "   "}{i + 1}. {s}'
        for i, s in enumerate(sentences_so_far)
    )
    return f"""You are a curious, literal-minded reader of a student essay, reading it one
sentence at a time. You have just read the sentence marked with "->" below,
in the context of everything read so far.

{read_so_far}

Write 3 to 4 short who/what/when/where/why/how questions that YOU, the reader,
want answered right now because of the sentence you just read.

Only ask questions a real reader would actually have at this point in the
text -- do not invent questions about things the essay has already answered.

For example, if a writer wrote, 'Social media has changed the way people communicate.' Some 
valid questions would be: 
    - How do you know? 
    - Who says that? 
    - When did social media change the way people communicate? 
    - How did it change the way people communicate? For better or worse? 

Respond with ONLY a JSON object of this exact form, no other text:
{{"questions": ["...", ...]}}"""


def build_checker_prompt(questions: list[str], next_sentence: str) -> str:
    numbered_questions = "\n".join(f"{i + 1}. {q}" for i, q in enumerate(questions))
    return f"""A reader asked the following questions after reading a sentence in a
student essay:

{numbered_questions}

Here is the very next sentence of the essay:
"{next_sentence}"

For each question, decide whether this next sentence, on its own, answers it.
Only mark a question answered if this sentence actually contains that answer --
do not assume information from later in the essay.

Respond with ONLY a JSON array of this exact form, no other text, with one
entry per question in the same order:
[{{"question": "...", "answered": true|false}}, ...]"""
