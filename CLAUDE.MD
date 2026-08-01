# CLAUDE.MD

## Project Identity

**Write Like a Reader** is a demo web app that gives composition students feedback 
on their expository writing.  A student uploads a paragraph or two from their writing; 
an LLM agent asks the Wh-questions (who, what, when, where, why, how many/often/long/frequent/much/many/etc) that
a reader of *this* essay would expect it to answer, another llm checks whether the text
answers them, and if not, flags the unanswered ones as inline annotations on the draft.

Guiding principle: good expository writing anticipates the reader's questions and answers them. 

**Core loop**
1. Student uploads a their from their expository essay.
2. Agent generates the reader questions relevant to this piece — not a number; the relevant subset depends on the essay.
3. Agent searches the text for each answer.
4. Answered questions are dropped silently; unanswered ones become inline
   annotations tied to the relevant passage.

**Users:** English 101/102 students, uploading their own drafts. Instructors
recommend the tool but aren't direct users. It's a learning tool — feedback
should build the habit of anticipating what a reader would ask, not just flag gaps.

**Stack:** Python + Gradio (`HighlightedText` for the annotation layer).

**Scope:** Demo / proof-of-concept, internal and investor-facing. Input caps
~1000 words / 20 sentences for now so don't hard-code the ceiling.

## Hard Stops
- Do not read `.env`, private keys, keypairs , or secret files.  


## Known Gotchas 

## Links 
Document Explaining what the Write Like a Reader process is: `docs/write_like_a_reader.md`
