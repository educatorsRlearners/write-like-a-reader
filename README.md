# Write Like a Reader

## Problem Statement
Walk into any English Composition classroom and you'll see a teacher 
explaining that you have to use details and reasons to support your ideas 
because, as is oft quoted, "In God we trust; everyone else has to bring 
evidence." 

Unfortunately, most students have a blind spot when it comes to providing 
these details and reasons because they know what they think and get get in 
the mind of their reader. 

That's where [Write Like a Reader](https://teachinglearninglearningteaching.wordpress.com/2015/01/26/learning-to-write-like-a-reader-teaching-students-how-to-edit-and-do-peer-review/) comes into play:
- a student gives their writing to a classmate
- the classmate reads the first sentence
- they think of 1-3 questions.  

 If the next sentence
   - *DOESN'T* answer the question(s), they write it/them down on their paper/draft
   - *DOES* answer the question, they don't write anything down 

When the student finishes the draft, they pass it back to their classmate who: 
- answers the questions
- edits their draft to integrate the new details and reasons strengthening their argument 
- or revises their argument because they've changed their position after reflecting on it. 


## Write Like a Reader APP
Simply put, this app mimics the classroom activity described above. 

- A student pastes or uploads a paragraph or two
-  an LLM agent (the
"Questioner") asks the Wh-questions a reader would have after each sentence,
- a second LLM agent (the "Answer-checker") checks whether the very next
sentence answers them. 
- Unanswered questions are highlighted inline on the
draft, so the student can revise their own draft — the tool flags gaps, it
doesn't fix them.

This is a demo / proof-of-concept.  It's
built for English 101/102 students uploading their own drafts; instructors
recommend it but aren't direct users of the app itself.


## How it works

1. You paste or upload (`.txt`) a draft into the Gradio UI (`app.py`).
2. `sentence_split.py` (`pysbd`) splits it into sentences.
3. `pipeline.py` makes exactly two calls to a local LLM (via
   [Ollama](https://ollama.com)) per submission: one batch "questioner" call
   asking, for every sentence at once, what a reader would still want to know
   at that point, then one batch "checker" call asking whether each
   sentence's *next* sentence answers its questions. (Earlier prototypes made
   one call pair per sentence, or tried running those calls concurrently with
   a thread pool — an empirical test found this Ollama setup serializes
   requests server-side regardless of client-side concurrency, so batching
   into two calls total was the actual fix; see `docs/specs/02_speed.md`.)
4. Answered questions are dropped silently. Unanswered ones are attached to
   that sentence as an annotation. Every question is capped at one sentence,
   e.g. "What new policy would the school board consider?"
5. `highlight.py` turns the annotations into Gradio `HighlightedText` spans;
   clicking a highlighted sentence shows its unanswered questions and a
   👍/👎 control to rate whether that sentence's flagged questions were good.
6. Every submitted draft, its generated questions, each LLM call's timing/
   token usage, and any feedback ratings are saved to a local SQLite database
   (`data/essays.db` by default) — the app's UI shows a data-retention notice
   to this effect. Storage failures never block the student from getting
   feedback (fail open).
7. `dashboard.py` is a separate Gradio app that reads the same database to
   show feedback-quality trends and LLM latency/token-cost charts.

There's no accounts, no auth, and no cloud LLM calls — everything runs
against a local Ollama model.

## Setup

Requires Python >=3.12 (see `pyproject.toml`).

1. Install dependencies:

   ```
   uv sync
   ```

2. Install [Ollama](https://ollama.com) and pull the model the app uses:

   ```
   brew install ollama
   ollama pull qwen2.5:3b
   ```

   Make sure the Ollama service is running (`ollama serve`, or just launch
   the Ollama app — it runs in the background) before starting the app
   below. The app calls the local Ollama API (`http://localhost:11434` by
   default), so no network access or API token is required at runtime.

   Optional env vars (set in a `.env` file if you want to override the
   defaults): `OLLAMA_MODEL` (default `qwen2.5:3b`), `OLLAMA_HOST` (default
   is Ollama's own local default), `OLLAMA_TIMEOUT` (seconds, default `60`),
   `DB_PATH` (default `data/essays.db`).

3. Run the tests:

   ```
   uv run pytest
   ```

4. Launch the app:

   ```
   uv run app.py
   ```

5. (Optional) Launch the dashboard, in a separate process, to review
   feedback quality and LLM latency/token cost:

   ```
   uv run dashboard.py
   ```

## Input limits

Two soft caps apply per draft: ~1000 words (`config.MAX_WORDS`) and 20
sentences (`config.MAX_SENTENCES`). Both warn but don't block — a longer
draft still runs, but takes longer and risks a larger, slower single batch
call. These caps exist specifically to keep a whole submission small enough
to fit in one questioner call and one checker call; see
`docs/specs/02_speed.md` for the token-budget reasoning behind them.

## Verifying the local model end-to-end

Before treating this as demo-ready, run one full pass with Ollama actually
serving the model:
- Confirm `ollama serve` is running and `ollama pull qwen2.5:3b` has
  finished.
- Paste in a short (1-2 paragraph) sample essay and confirm the Questioner
  asks sensible questions and the Answer-checker's answered/unanswered calls
  look right.
- Stop Ollama and confirm the app fails gracefully (matching the existing
  backend-unreachable handling in `pipeline.py`) rather than crashing.