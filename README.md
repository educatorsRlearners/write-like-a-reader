# write-like-a-reader

A demo app that gives composition students feedback on their expository writing.
A student pastes or uploads a paragraph or two; an LLM agent (the "Questioner") asks the
Wh-questions a reader would have after each sentence, and a second LLM agent (the
"Answer-checker") checks whether the very next sentence answers them. Unanswered
questions are highlighted inline on the draft, so the student can revise their own
draft — the tool flags gaps, it doesn't fix them.

See `CLAUDE.MD` for the project brief and `docs/write_like_a_reader.md` for the
classroom activity this automates.

## Setup

1. Install dependencies and the spaCy model:

   ```
   uv sync
   uv run python -m spacy download en_core_web_sm
   ```

2. Install [Ollama](https://ollama.com) and pull the model the app uses:

   ```
   brew install ollama
   ollama pull qwen2.5:3b
   ```

   Make sure the Ollama service is running (`ollama serve`, or just launch the
   Ollama app — it runs in the background) before starting the app below. The
   app calls the local Ollama API (`http://localhost:11434` by default), so no
   network access or API token is required.

   Optional env vars (set in a `.env` file if you want to override the
   defaults): `OLLAMA_MODEL` (default `qwen2.5:3b`), `OLLAMA_HOST` (default is
   Ollama's own local default), `OLLAMA_TIMEOUT` (seconds, default `60`).

3. Run the tests:

   ```
   uv run pytest
   ```

4. Launch the app:

   ```
   uv run app.py
   ```

## Verifying the local model end-to-end

Before treating this as demo-ready, run one full pass with Ollama actually
serving the model:
- Confirm `ollama serve` is running and `ollama pull qwen2.5:3b` has finished.
- Paste in a short (1-2 paragraph) sample essay and confirm the Questioner asks
  sensible questions and the Answer-checker's answered/unanswered calls look right.
- Stop Ollama and confirm the app fails gracefully (matching the existing
  backend-unreachable handling in `pipeline.py`) rather than crashing.
