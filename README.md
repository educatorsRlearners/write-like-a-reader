# write-like-a-reader

A demo app that gives composition students feedback on their expository essays.
A student pastes or uploads a draft; an LLM agent (the "Questioner") asks the
Wh-questions a reader would have after each sentence, and a second LLM agent (the
"Answer-checker") checks whether the very next sentence answers them. Unanswered
questions are highlighted inline on the draft, color-coded by category (detail vs.
reason), so the student can revise their own draft — the tool flags gaps, it
doesn't fix them.

See `CLAUDE.MD` for the project brief and `docs/write_like_a_reader.md` for the
classroom activity this automates.

## Setup

1. Install dependencies and the spaCy model:

   ```
   uv sync
   uv run python -m spacy download en_core_web_sm
   ```

2. Create a `.env` file in the repo root with your Hugging Face token:

   ```
   HF_TOKEN=hf_...
   ```

   Get a token at https://huggingface.co/settings/tokens. The app calls the
   Hugging Face Inference API (`huggingface_hub.InferenceClient`), so this needs
   a network that can actually reach `huggingface.co`.

3. Run the tests:

   ```
   uv run pytest
   ```

4. Launch the app:

   ```
   uv run app.py
   ```

## Known limitation of this build

This app was built in a sandboxed environment whose network policy blocks
`huggingface.co` outright (not just missing credentials — the domain itself was
unreachable). Because of that, **the live Hugging Face-backed feedback loop
(the Questioner and Answer-checker actually calling a model) was never verified
end-to-end** in that environment. Everything that doesn't need network access —
sentence splitting, the retry/JSON-parsing logic in `llm_client.py`, the pipeline's
sentence-loop logic, the highlighting/annotation logic, and the Gradio UI itself
(including its graceful-failure behavior when the backend is unreachable) — was
tested and confirmed working, including in a live browser.

Before treating this as demo-ready, run one full pass with a real `HF_TOKEN` on a
network that can reach `huggingface.co`:
- Paste in a short (1-2 paragraph) sample essay and confirm the Questioner asks
  sensible questions and the Answer-checker's answered/unanswered calls look right.
- Confirm `MODEL_NAME` in `config.py` (defaults to `Qwen/Qwen2.5-7B-Instruct`) is
  still being served on HF's free Inference API tier — free-tier model
  availability shifts over time, so this needs re-checking against HF's current
  model list rather than assumed from the default.
