QUESTIONER_RETRY = (
    "Your previous response was not valid JSON. Respond with ONLY a JSON object "
    "mapping each sentence index (as a string) to an array of question strings, "
    'of the form {"0": ["<question text>", "<question text>"], "1": [], ...}, '
    "no other text."
)

CHECKER_RETRY = (
    "Your previous response was not valid JSON. Respond with ONLY a JSON object "
    "mapping each sentence index (as a string) to an array of true/false values, "
    "one per question in that sentence's list, of the form "
    '{"0": [true, false], "1": [true]}, no other text.'
)

_FORMATTING_RULES = """Formatting rules for every question you write:
- Write the full question with proper grammar and punctuation.
- Keep each question to one sentence.
- Phrase every question as a genuine, direct question (not a statement).
- Never write placeholder or filler text (e.g. "...") as a question. Every
  question must be a real, complete question about the sentence you read.
"""


def build_batch_questioner_prompt(sentences: list[str]) -> str:
    numbered = "\n".join(f"{i}. {s}" for i, s in enumerate(sentences))
    prompt = f"""You are a curious, literal-minded reader of a student essay, reading it one
    sentence at a time. Here is one or two paragraphs from an essay, one sentence per line, numbered
    starting at 0:
    
    {numbered}
    
    For EACH sentence index above, write one to three short questions
    that YOU, the reader, would want answered right after reading that
    sentence, given everything you'd have read up through that point (sentences
    0 through that index). 
    
    Only ask questions a real reader would actually have
    at that point in the text; do not invent questions about things the essay
    has already answered earlier. 

    For example, if a writer wrote, 'Social media has changed the way people
    communicate.' Some valid questions would be:
        - How did it change the way people communicate? For better or worse?
        - Who says that?
        - What type of impact have those changes made?
    
    Do not ask questions no one would ask because they are obvious or stupid.
    For example, if a writer wrote, 'The cat was sitting on a mat,'
    some invalid questions would be:
        - Where was the cat sitting?
        - What was the cat doing on the mat?
        - What was under the cat?
        - What was lying on the mat?

    Do not ask a who/what question whose answer is the subject the sentence
    already names. If a writer wrote, 'Social media has changed the way
    people communicate,' asking "Who changed the way people communicate?"
    or "What changed the way people communicate" would be redundant -- 
    the sentence already says social media did. Instead,
    ask about a detail the sentence doesn't answer yet, e.g. "How has
    social media changed the way people communicate?"

    Additionally, check that your question makes sense. For example, if the sentence is: 
    "This would help students focus better by resisting the sirens call of social media.' a question like
    "How does this new policy resist the siren's call of social media." doesn't make any sense. Instead, ask
    something like "How would this new policy improve student's focus?"  
    
    If a sentence raises no new reader questions,
    its array can be empty.
    
    {_FORMATTING_RULES}
        
    Respond with ONLY a JSON object mapping each sentence index (as a string) to
    an array of question strings, of this exact form, no other text:
    {{"0": ["<question text>", "<question text>"], "1": ["<question text>"], ...}}"""

    return prompt


def build_batch_checker_prompt(
    question_map: dict[int, list[str]], sentences: list[str]
) -> str:
    sections = []
    for i in sorted(question_map):
        questions = question_map[i]
        if not questions:
            continue
        numbered_questions = "\n".join(f"    {j}. {q}" for j, q in enumerate(questions))
        sections.append(
            f"Sentence {i} questions (checked against the next sentence, "
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
