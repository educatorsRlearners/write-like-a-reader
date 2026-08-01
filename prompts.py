QUESTIONER_RETRY = (
    "Your previous response was not valid JSON. Respond with ONLY a JSON object "
    'mapping each sentence index (as a string) to an array of question strings, '
    'of the form {"0": ["...", "..."], "1": [], ...}, no other text.'
)

CHECKER_RETRY = (
    "Your previous response was not valid JSON. Respond with ONLY a JSON object "
    'mapping each sentence index (as a string) to an array of true/false values, '
    'one per question in that sentence\'s list, of the form '
    '{"0": [true, false], "1": [true]}, no other text.'
)

_FORMATTING_RULES = """Formatting rules for every question you write:
- Start the question with its category as a literal prefix, followed by a
  colon and a space: "Who:", "What:", "When:", "Where:", "Why:", or
  "How many/much/long/often:" (pick whichever "how" variant actually fits --
  e.g. "How many:", "How long:", "How often:" -- rather than always writing
  the full slash-separated list). Use the prefix that matches what the
  question is actually asking about, not just the first Wh-word that comes
  to mind.
- Keep each question to three sentences or fewer. One sentence is fine and
  often best; use a second or third only when necessary framing (e.g. "X
  says Y. Where's that from?")."""


def build_batch_questioner_prompt(sentences: list[str]) -> str:
    numbered = "\n".join(f"{i}. {s}" for i, s in enumerate(sentences))
    return f"""You are a curious, literal-minded reader of a student essay, reading it one
sentence at a time. Here is the whole essay, one sentence per line, numbered
starting at 0:

{numbered}

For EACH sentence index above, write 3 to 4 short who/what/when/where/why/how
questions that YOU, the reader, would want answered right after reading that
sentence, given everything you'd have read up through that point (sentences
0 through that index). Only ask questions a real reader would actually have
at that point in the text -- do not invent questions about things the essay
has already answered earlier. If a sentence raises no new reader questions,
its array can be empty.

{_FORMATTING_RULES}

For example, if a writer wrote, 'Social media has changed the way people
communicate.' Some valid questions would be:
    - How: How did it change the way people communicate? For better or worse?
    - Who: Who says that?
    - When: When did social media change the way people communicate?

Respond with ONLY a JSON object mapping each sentence index (as a string) to
an array of question strings, of this exact form, no other text:
{{"0": ["...", ...], "1": ["...", ...], ...}}"""


def build_batch_checker_prompt(question_map: dict[int, list[str]], sentences: list[str]) -> str:
    sections = []
    for i in sorted(question_map):
        questions = question_map[i]
        if not questions:
            continue
        numbered_questions = "\n".join(f"    {j}. {q}" for j, q in enumerate(questions))
        sections.append(
            f'Sentence {i} questions (checked against the next sentence, '
            f'"{sentences[i + 1]}"):\n{numbered_questions}'
        )
    joined = "\n\n".join(sections)
    return f"""A reader asked the following questions after reading certain sentences in a
student essay. For each sentence's questions, decide whether the sentence
listed right after it, on its own, answers each question. Only mark a
question answered if that next sentence actually contains that answer -- do
not assume information from elsewhere in the essay.

{joined}

Respond with ONLY a JSON object mapping each sentence index (as a string) to
an array of true/false values, one per question in that sentence's list, in
the same order as listed above, of this exact form, no other text:
{{"0": [true, false], "1": [true], ...}}"""
