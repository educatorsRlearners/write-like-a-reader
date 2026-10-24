# Write Like a Reader

[![Python](https://img.shields.io/badge/python-%3E%3D3.12-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](./LICENSE)
[![Tests: pytest](https://img.shields.io/badge/tests-pytest-0A9EDC?logo=pytest&logoColor=white)](https://docs.pytest.org/)
[![Lint: ruff](https://img.shields.io/badge/lint-ruff-D7FF64?logo=ruff&logoColor=black)](https://docs.astral.sh/ruff/)
[![Built with Gradio](https://img.shields.io/badge/UI-Gradio-F97316?logo=gradio&logoColor=white)](https://www.gradio.app/)
[![Managed with uv](https://img.shields.io/badge/packaging-uv-DE5FE9?logo=uv&logoColor=white)](https://docs.astral.sh/uv/)
![LLM providers](https://img.shields.io/badge/LLM-Ollama%20%7C%20OpenAI%20%7C%20Anthropic%20%7C%20DeepSeek%20%7C%20Grok-000000)
![Docker Compose](https://img.shields.io/badge/deploy-Docker%20Compose-2496ED?logo=docker&logoColor=white)

> An AI peer reviewer that reads your draft sentence by sentence and asks the questions your reader would. It points at the gaps and leaves you to fill them.

**The problem.** Every English Composition teacher says to back ideas with
details and reasons: "In God we trust; everyone else has to bring evidence."
Yet most students cannot see the gaps in their own drafts. They know what they
think but cannot imagine what their reader does not know.

[Write Like a
Reader](https://teachinglearninglearningteaching.wordpress.com/2015/01/26/learning-to-write-like-a-reader-teaching-students-how-to-edit-and-do-peer-review/)
is a classroom peer-review exercise. A classmate reads one sentence and thinks
of one to three questions a reader would now have. If the **next** sentence
answers them, the classmate writes nothing; if not, the classmate notes the
question in the margin.

This app mimics the exercise. A student pastes or uploads a paragraph or two.
An LLM "Questioner" generates the Wh-questions a reader would have after each
sentence, and an LLM "Answer-checker" decides whether the very next sentence
answers them. The app highlights unanswered questions inline so the student can
revise. **It flags gaps; it does not fix them.**

This repo is a demo and proof of concept for high school or English 101/102 students working on
their own drafts. It has no accounts and no auth. By default it makes no cloud
calls: everything runs against a local [Ollama](https://ollama.com) model, and
no draft text leaves the machine. A developer may opt into a cloud provider
(OpenAI, Anthropic, DeepSeek, or Grok); the draft text is then sent to that
vendor.

https://github.com/user-attachments/assets/2e09036e-fee9-4253-8cc4-63adc4799bf7

## Installation

Requires **Python ≥ 3.12**.

macOS & Linux (or Windows via WSL / Git Bash):

```sh
make run
```

This installs [uv](https://docs.astral.sh/uv/) and the dependencies, installs
and starts Ollama, and pulls the model, skipping any step already done. It then
launches the app at <http://127.0.0.1:7860>.

Windows (native, without a POSIX shell) — use Docker Compose:

```sh
mkdir -p data && chmod 777 data   # once, so the non-root containers can write to it
docker compose up --build
```

The first run pulls the `ollama/ollama` image and the `qwen2.5:3b` model into a
persistent volume before starting the app and dashboard, which can take several
minutes; later runs reuse the cached volume. The app runs at
<http://localhost:7860>, the dashboard at <http://localhost:7861>. Drafts
persist to `./data/essays.db` on the host. Stop with `docker compose down`; add
`-v` to delete the downloaded model and start fresh.

## Usage example

1. Open <http://127.0.0.1:7860> and paste a draft, or upload a `.txt` file.
2. Submit it. The app highlights sentences with unanswered reader questions.
3. Click a highlighted sentence to see its questions. Rate them 👍 or 👎 to say
   whether they were good ones.
4. Revise the draft to answer the questions, either by adding detail or by
   rethinking the argument. You may also download the annotated `.txt`, which
   inserts the unanswered questions in brackets.

Each question is one sentence, e.g. "What new policy would the school board
consider?" The app drops answered questions without comment.

<details>
<summary><strong>Make targets</strong></summary>

`make help` lists them all:

| Target | What it does |
| --- | --- |
| `make run` | Install everything and launch the app (default) |
| `make test` | Run the test suite (`uv run pytest`) |
| `make dashboard` | Launch the feedback/latency dashboard on port 7861 |
| `make docker-up` / `make docker-down` | Start / stop the Docker Compose stack |
| `make clean` | Remove cached bytecode and the pytest cache |

</details>

<details>
<summary><strong>Choosing an LLM provider</strong></summary>

The LLM backend is pluggable. Configuration has three parts:

- **`config.py`** — app behavior: `LLM_PROVIDER`
  (`ollama` | `openai` | `anthropic` | `deepseek` | `grok`, default `ollama`),
  plus `LLM_TIMEOUT`, `LLM_MAX_TOKENS`, and `LLM_NUM_CTX`. Each provider has a
  default model, so setting `LLM_PROVIDER` is enough; set `LLM_MODEL_OVERRIDE`
  only to choose a different model. Edit and commit these values. The default,
  `ollama`, needs no changes and no credentials.
- **`.env`** — secrets only: the API key for your provider. Git ignores it.
- **Environment variables** — deployment bindings: `LLM_BASE_URL` (the API
  endpoint; docker-compose points it at the in-cluster Ollama, and a cloud user
  can point it at an Azure or proxy gateway), `APP_HOST` / `APP_PORT`,
  `DASHBOARD_HOST` / `DASHBOARD_PORT`, and `DB_PATH`. Each has a local default
  in `config.py`, which docker-compose overrides for the container.

| Provider | Default model | API key (`.env`) | Install |
| --- | --- | --- | --- |
| `ollama` | `qwen2.5:3b` | — (local, no key) | bundled |
| `openai` | `gpt-4o-mini` | `OPENAI_API_KEY` | `uv sync --extra openai` |
| `anthropic` | `claude-sonnet-5` | `ANTHROPIC_API_KEY` | `uv sync --extra anthropic` |
| `deepseek` | `deepseek-chat` | `DEEPSEEK_API_KEY` | `uv sync --extra openai` |
| `grok` | `grok-4` | `GROK_API_KEY` (or `XAI_API_KEY`) | `uv sync --extra openai` |

DeepSeek and Grok are OpenAI-compatible. Their base URLs default to
`https://api.deepseek.com` and `https://api.x.ai/v1`.

To switch to a cloud provider:

1. Set the provider in `config.py`; add `LLM_MODEL_OVERRIDE = "..."` to change
   the model:

   ```python
   # config.py
   LLM_PROVIDER = "openai"
   ```

2. Put the API key in `.env` (copy `.env.example` first):

   ```sh
   cp .env.example .env
   ```

   ```
   # .env — secrets only
   OPENAI_API_KEY=sk-...
   ```

   `config.py` calls `load_dotenv()` at startup, so each vendor SDK reads its
   key from the environment. Git ignores `.env`; never commit it.

3. Install the SDK and run:

   ```sh
   uv sync --extra openai
   uv run app.py
   ```

To run Docker Compose against a cloud provider, set `LLM_PROVIDER` in
`config.py`, put the API key in `.env` (the `app` service loads it through
`env_file`), and drop the `ollama` and `ollama-pull` services from
`docker-compose.yml`. The `environment:` block on the `app` service holds
deployment bindings only.

The two-call design and the input caps apply to every provider. With a cloud
provider, the draft text goes to that vendor; only the default `ollama` path
keeps everything on the machine.

</details>

<details>
<summary><strong>Input limits</strong></summary>

Two soft caps apply to each draft: about 1000 words (`config.MAX_WORDS`) and 20
sentences (`config.MAX_SENTENCES`). Both warn but do not block. A longer draft
still runs but takes longer and risks a larger, slower batch call. The caps keep
a whole submission small enough to fit in one questioner call and one checker
call.

Using *Write Like a Reader* on more than a couple of paragraphs is overkill. The
aim is to make students **aware** of the concept, so that they internalize the
process and stop needing the app.

</details>

## How it works

The app splits a draft into sentences, then makes **two** batched LLM calls for
the whole submission. The first asks what a reader would still want to know
after each sentence; the second checks whether the next sentence answers it.
The app highlights unanswered questions inline.

<details>
<summary><strong>Pipeline steps</strong></summary>

1. `app.py` (Gradio) takes the pasted or uploaded draft.
2. `sentence_split.py` (`pysbd`) splits it into sentences.
3. `pipeline.py` makes **exactly two** LLM calls per submission, not one pair
   per sentence. A batched "questioner" call asks, for every sentence at once,
   what a reader would still want to know at that point. A batched "checker"
   call then asks whether each sentence's *next* sentence answers its
   questions. (Earlier prototypes made one call pair per sentence, or ran the
   calls concurrently in a thread pool. Testing showed that this Ollama setup
   serializes requests on the server whatever the client does, so batching into
   two calls was the real fix. See
   [`docs/write_like_a_reader.md`](docs/write_like_a_reader.md).)
4. The pipeline attaches each unanswered question to its sentence as an
   annotation.
5. `highlight.py` turns the annotations into Gradio `HighlightedText` spans.
6. The app saves every submitted draft, its generated questions, each LLM
   call's timing and token usage, and any feedback ratings to a local SQLite
   database (`data/essays.db` by default). The UI shows a data-retention
   notice. A storage failure never blocks the student from getting feedback
   (fail open).
7. `dashboard.py`, a separate Gradio app over the same database, shows
   feedback-quality trends and LLM latency and token-cost charts. Each
   `llm_calls` row carries the provider and model that served it
   (`config.LLM_PROVIDER` / `config.LLM_MODEL` at call time), and the
   dashboard's "Provider / Model" tab compares duration, token usage, and
   failure rate across them. Rows written before a provider switch keep their
   old tag; rows from before this feature, or from a recreated DB, are
   untagged.

</details>

<details>
<summary><strong>Modules</strong></summary>

The code is a flat set of top-level modules, wired together by two Gradio
`Blocks` apps that share one SQLite database:

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

</details>

## Development setup

```sh
uv sync              # install dependencies (add --extra openai / --extra anthropic for cloud SDKs)
uv run pytest        # run the tests
uv run app.py        # main app on :7860
uv run dashboard.py  # dashboard on :7861
```

- Lint and format with [ruff](https://docs.astral.sh/ruff/).
- The SQLite database lives at `data/essays.db`; set `DB_PATH` to override. The
  project has no migration infrastructure, so a schema change means recreating
  the file.
- There are no accounts and no auth. Storage is fail-open by design: a
  persistence error never blocks a student from seeing feedback.

## Release History

No tagged releases yet. See the [commit history](../../commits/main) for
changes.

## Meta

Evan Simpson – [@educatorsRlearners](https://github.com/educatorsRlearners)

Distributed under the MIT license. See [`LICENSE`](./LICENSE) for more
information.

<https://github.com/educatorsRlearners/write-like-a-reader>

## Contributing

1. Fork it (<https://github.com/educatorsRlearners/write-like-a-reader/fork>)
2. Create your feature branch (`git checkout -b feature/fooBar`)
3. Commit your changes (`git commit -am 'Add some fooBar'`)
4. Push to the branch (`git push origin feature/fooBar`)
5. Create a new Pull Request
