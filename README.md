<h1 align="center">Write Like a Reader</h1>

<p align="center">
  <em>An AI peer reviewer that reads your draft sentence by sentence and asks 
  the questions your reader would; it points at the gaps, it doesn't fill
  them in for you.</em>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-%3E%3D3.12-3776AB?logo=python&logoColor=white" alt="Python >=3.12">
  <a href="./LICENSE"><img src="https://img.shields.io/badge/license-MIT-green" alt="License: MIT"></a>
  <img src="https://img.shields.io/badge/tests-pytest-0A9EDC?logo=pytest&logoColor=white" alt="Tests: pytest">
  <img src="https://img.shields.io/badge/lint-ruff-D7FF64?logo=ruff&logoColor=black" alt="Lint: ruff">
  <img src="https://img.shields.io/badge/UI-Gradio-F97316?logo=gradio&logoColor=white" alt="Built with Gradio">
  <img src="https://img.shields.io/badge/packaging-uv-DE5FE9?logo=uv&logoColor=white" alt="Managed with uv">
  <img src="https://img.shields.io/badge/LLM-Ollama%20%7C%20OpenAI%20%7C%20Anthropic%20%7C%20DeepSeek%20%7C%20Grok-000000" alt="LLM providers">
  <img src="https://img.shields.io/badge/deploy-Docker%20Compose-2496ED?logo=docker&logoColor=white" alt="Docker Compose">
</p>

https://github.com/user-attachments/assets/2e09036e-fee9-4253-8cc4-63adc4799bf7

---

## Contents

- [What it is](#what-it-is)
- [How it works](#how-it-works)
- [Quick start](#quick-start)
- [Choosing an LLM provider](#choosing-an-llm-provider)
- [Running with Docker](#running-with-docker)
- [Input limits](#input-limits)
- [Architecture](#architecture)
- [Development](#development)
- [License](#license)

## What it is

**The problem.** Walk into any English Composition classroom and you'll hear
that you have to back your ideas with details and reasons — "In God we trust;
everyone else has to bring evidence." But most students have a blind spot here:
they know what they think, and they can't get into the head of their reader, so
they leave the gaps invisible to themselves.

**The classroom fix.** [Write Like a
Reader](https://teachinglearninglearningteaching.wordpress.com/2015/01/26/learning-to-write-like-a-reader-teaching-students-how-to-edit-and-do-peer-review/)
is a peer-review exercise:

- a student hands their draft to a classmate;
- the classmate reads one sentence and thinks of 1–3 questions a reader would
  now have;
- if the **next** sentence answers them, they write nothing; if it doesn't,
  they note the question in the margin;
- repeat to the end, then hand it back so the writer can answer the questions —
  by adding detail, or by rethinking the argument.

**This app** mimics that exercise. A student pastes or uploads a paragraph or
two; an LLM "Questioner" generates the Wh-questions a reader would have after each
sentence; an LLM "Answer-checker" decides whether the very next sentence
answers them. Unanswered questions are highlighted inline on the draft so the
student can revise; **the tool flags gaps, it doesn't fix them.**

It's a demo / proof-of-concept for English 101/102 students working on their
own drafts. There are no accounts and no auth. By default there are also no
cloud calls — everything runs against a local [Ollama](https://ollama.com)
model and no draft text leaves the machine. A developer can opt into a cloud
provider (OpenAI, Anthropic, DeepSeek, or Grok), in which case the draft text
is sent to that vendor. See [Choosing an LLM
provider](#choosing-an-llm-provider).

## How it works

1. You paste or upload (`.txt`) a draft into the Gradio UI (`app.py`).
2. `sentence_split.py` (`pysbd`) splits it into sentences.
3. `pipeline.py` makes **exactly two** LLM calls per submission — not one pair
   per sentence: one batched "questioner" call asking, for every sentence at
   once, what a reader would still want to know at that point, then one batched
   "checker" call asking whether each sentence's *next* sentence answers its
   questions. (Earlier prototypes made one call pair per sentence, or ran the
   calls concurrently with a thread pool; an empirical test found this Ollama
   setup serializes requests server-side regardless of client concurrency, so
   batching into two calls total was the actual fix. See
   [`docs/write_like_a_reader.md`](docs/write_like_a_reader.md).)
4. Answered questions are dropped silently. Each unanswered one is attached to
   its sentence as an annotation. Questions are capped at one sentence each,
   e.g. "What new policy would the school board consider?"
5. `highlight.py` turns the annotations into Gradio `HighlightedText` spans.
   Clicking a highlighted sentence shows its unanswered questions and a 👍 / 👎
   control to rate whether that sentence's flagged questions were good.
6. Every submitted draft, its generated questions, each LLM call's
   timing/token usage, and any feedback ratings are saved to a local SQLite
   database (`data/essays.db` by default) — the UI shows a data-retention
   notice. Storage failures never block the student from getting feedback
   (fail open).
7. `dashboard.py` is a separate Gradio app over the same database, showing
   feedback-quality trends and LLM latency/token-cost charts. Each `llm_calls`
   row is tagged with the provider and model that served it
   (`config.LLM_PROVIDER` / `config.LLM_MODEL` at call time), and the
   dashboard's "Provider / Model" tab compares duration, token usage, and
   failure rate across them. Rows written before a provider switch keep their
   old tag; rows from before this feature (or a recreated DB) are untagged.

## Quick start

Requires **Python ≥ 3.12**. On macOS or Linux (or Windows via WSL / Git Bash):

```
make run
```

This installs [uv](https://docs.astral.sh/uv/) and dependencies, installs and
starts Ollama and pulls the model if any of those aren't set up already, then
launches the app at <http://127.0.0.1:7860>. On native Windows without a POSIX
shell, use the [Docker](#running-with-docker) path instead.

Other targets (`make help` lists them all):

| Target | What it does |
| --- | --- |
| `make run` | Install everything and launch the app (default) |
| `make test` | Run the test suite (`uv run pytest`) |
| `make dashboard` | Launch the feedback/latency dashboard on port 7861 |
| `make docker-up` / `make docker-down` | Start / stop the Docker Compose stack |
| `make clean` | Remove cached bytecode and the pytest cache |

To change the model, Ollama URL, timeout, or ports, edit `config.py` — it holds
all non-secret settings as plain Python values.

## Choosing an LLM provider

The LLM backend is pluggable. Configuration splits three ways:

- **`config.py`** — how the app behaves: `LLM_PROVIDER`
  (`ollama` | `openai` | `anthropic` | `deepseek` | `grok`, default `ollama`),
  plus `LLM_TIMEOUT`, `LLM_MAX_TOKENS`, `LLM_NUM_CTX`. Each provider has a
  default model, so setting `LLM_PROVIDER` is enough; set `LLM_MODEL_OVERRIDE`
  only to pick a different model. Edit and commit these. The default `ollama`
  needs no changes and no credentials.
- **`.env`** — secrets only: the API key for your provider, gitignored.
- **Environment variables** — deployment bindings: `LLM_BASE_URL` (the API
  endpoint — docker-compose points it at the in-cluster Ollama; a cloud user
  can point it at an Azure / proxy gateway), `APP_HOST` / `APP_PORT`,
  `DASHBOARD_HOST` / `DASHBOARD_PORT`, `DB_PATH`. Each has a local default in
  `config.py`; docker-compose overrides them for the container.

| Provider | Default model | API key (`.env`) | Install |
| --- | --- | --- | --- |
| `ollama` | `qwen2.5:3b` | — (local, no key) | bundled |
| `openai` | `gpt-4o-mini` | `OPENAI_API_KEY` | `uv sync --extra openai` |
| `anthropic` | `claude-sonnet-5` | `ANTHROPIC_API_KEY` | `uv sync --extra anthropic` |
| `deepseek` | `deepseek-chat` | `DEEPSEEK_API_KEY` | `uv sync --extra openai` |
| `grok` | `grok-4` | `GROK_API_KEY` (or `XAI_API_KEY`) | `uv sync --extra openai` |

DeepSeek and Grok are OpenAI-compatible; their base URLs default to
`https://api.deepseek.com` and `https://api.x.ai/v1`.

### Switching to a cloud provider

1. In `config.py`, set the provider (add `LLM_MODEL_OVERRIDE = "..."` to change
   the model):

   ```python
   # config.py
   LLM_PROVIDER = "openai"
   ```

2. Put the API key in `.env` (copy `.env.example` first):

   ```
   cp .env.example .env
   ```

   ```
   # .env — secrets only
   OPENAI_API_KEY=sk-...
   ```

   `config.py` calls `load_dotenv()` at startup, so each vendor SDK reads its
   key straight from the environment. `.env` is gitignored; never commit it.

3. Install the SDK and run:

   ```
   uv sync --extra openai
   uv run app.py
   ```

The two-calls-per-submission design and the input caps apply to every provider.
With a cloud provider the draft text is sent to that vendor; only the default
`ollama` path keeps everything on the machine.

## Running with Docker

As an alternative to the local `uv` setup, the whole stack (Ollama + app +
dashboard) runs in containers via Docker Compose.

1. Create the data directory and open its permissions once, so the non-root
   containers can write to it:

   ```
   mkdir -p data && chmod 777 data
   ```

2. Build and start everything:

   ```
   docker compose up --build
   ```

   The first run pulls the `ollama/ollama` image and the `qwen2.5:3b` model
   into a persistent volume before starting the app and dashboard — this can
   take several minutes. Subsequent runs reuse the cached volume.

   To run against a cloud provider instead: set `LLM_PROVIDER` in `config.py`,
   put the API key in `.env` (the `app` service loads it via `env_file`), and
   drop the `ollama` / `ollama-pull` services from `docker-compose.yml`. The
   `environment:` block on the `app` service is deployment bindings only.

3. Open the app at <http://localhost:7860> and the dashboard at
   <http://localhost:7861>.

4. Drafts persist to `./data/essays.db` on the host, same as the local setup.

5. Stop with `docker compose down` (add `-v` to also delete the downloaded
   model and start fresh).

## Input limits

Two soft caps apply per draft: ~1000 words (`config.MAX_WORDS`) and 20
sentences (`config.MAX_SENTENCES`). Both warn but don't block — a longer draft
still runs, but takes longer and risks a larger, slower single batch call.
These caps exist to keep a whole submission small enough to fit in one
questioner call and one checker call.

Doing *Write Like a Reader* for anything longer than a couple of paragraphs is
overkill anyway; the idea is to make students **aware** of the concept so they
internalize the process and, hopefully, stop needing the app.

## Architecture

Everything is a flat set of top-level modules wired together by two Gradio
`Blocks` apps sharing one SQLite database:

| Module | Responsibility |
| --- | --- |
| `app.py` | Student-facing UI; orchestrates save → `pipeline.run()` → render → annotated `.txt` download |
| `pipeline.py` | Core logic: two batched LLM calls, per-index fail-open parsing |
| `prompts.py` | Builds the questioner / checker prompts and their JSON-retry variants |
| `llm_providers.py` | Pluggable LLM layer — one adapter per provider, normalized to `LLMResponse` |
| `llm_client.py` | Provider-agnostic JSON-call wrapper with retry/backoff |
| `sentence_split.py` | `pysbd` wrapper producing `Sentence` objects with char offsets |
| `highlight.py` | `PipelineResult` → `HighlightedText` spans + annotated draft text |
| `storage.py` | SQLite persistence (`essays`, `questions`, `llm_calls`, `feedback`); every write is fail-open |
| `dashboard.py` | Read-only Gradio app over the same DB |
| `config.py` | Single source of configuration (app config / deployment bindings / `.env` secrets) |

See [`CLAUDE.md`](CLAUDE.md) for the full module-by-module walkthrough and data
flow.

## Development

```
uv sync            # install dependencies (add --extra openai / --extra anthropic for cloud SDKs)
uv run pytest      # run the tests
uv run app.py      # main app on :7860
uv run dashboard.py  # dashboard on :7861
```

- Lint/format with [ruff](https://docs.astral.sh/ruff/).
- The SQLite database lives at `data/essays.db` (`DB_PATH` to override). There
  is no migration infra — a schema change means recreating the file.
- No accounts, no auth. Storage is fail-open by design: a persistence error
  never blocks a student from seeing feedback.

## License

[MIT](./LICENSE) © 2026 Evan Simpson
