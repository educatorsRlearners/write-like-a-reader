# Write Like a Reader

https://github.com/user-attachments/assets/81615429-00bd-4978-b665-e2d077752118

## Problem Statement
Walk into any English Composition classroom and you'll see a teacher 
explaining that you have to use details and reasons to support your ideas 
because, as is oft quoted, "In God we trust; everyone else has to bring 
evidence." 

Unfortunately, most students have a blind spot when it comes to providing 
these details and reasons because they know what they think and can't get in 
the mind of their reader. 

That's where [Write Like a Reader](https://teachinglearninglearningteaching.wordpress.com/2015/01/26/learning-to-write-like-a-reader-teaching-students-how-to-edit-and-do-peer-review/) comes into play:
- a student gives their writing to a classmate
- the classmate reads the first sentence
- they think of 1-3 questions.  

 If the next sentence
   - *DOESN'T* answer the question(s), they write it/them down on their paper/draft
   - *DOES* answer the question, they don't write anything down

The classmate then repeats the process for the rest of the draft and when they finish the draft, 
they pass it back to their classmate who: 
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
3. `pipeline.py` makes exactly two calls to an LLM per submission (by default
   a local model via [Ollama](https://ollama.com); see
   [Choosing an LLM provider](#choosing-an-llm-provider)): one batch
   "questioner" call
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

There's no accounts and no auth. By default there are also no cloud LLM
calls — everything runs against a local Ollama model and no draft text
leaves the machine. A developer can opt into a cloud provider (OpenAI,
Anthropic, DeepSeek) instead; in that case the draft text is sent to that
vendor. See [Choosing an LLM provider](#choosing-an-llm-provider).

## Setup

Requires Python >=3.12. On macOS or Linux (or Windows via WSL/Git Bash),
that's all you need:

```
make run
```

This installs [uv](https://docs.astral.sh/uv/) and dependencies, installs
and starts Ollama and pulls the model, if any of those aren't already set
up, and launches the app at http://127.0.0.1:7860. On native Windows
without a POSIX shell, use the [Docker](#running-with-docker) path below
instead.

Other useful targets — run `make help` to see the full list:

- `make test` — run the test suite
- `make dashboard` — launch the dashboard (separate process, reviews
  feedback quality and LLM latency/token cost)
- `make clean` — remove cached bytecode and test caches

To change the model, Ollama URL, timeout, or ports, edit `config.py` — it
holds all non-secret settings as plain Python values. See the next section
for switching providers.

## Choosing an LLM provider

The LLM backend is pluggable. Configuration splits three ways:

- **`config.py`** — how the app behaves. `LLM_PROVIDER`
  (`ollama` | `openai` | `anthropic` | `deepseek` | `grok`, default
  `ollama`), plus `LLM_TIMEOUT`, `LLM_MAX_TOKENS`, `LLM_NUM_CTX`. Each
  provider has a default model (`DEFAULT_MODELS`), so setting `LLM_PROVIDER`
  is enough; set `LLM_MODEL_OVERRIDE` only to pick a different model. Edit
  and commit these. The default `ollama` needs no changes and no credentials.
- **`.env`** — secrets only. The API key for your provider
  (`OPENAI_API_KEY` / `ANTHROPIC_API_KEY` / `DEEPSEEK_API_KEY` /
  `GROK_API_KEY`), gitignored.
- **Environment variables** — deployment bindings: `LLM_BASE_URL` (the API
  endpoint — docker-compose points it at the in-cluster Ollama; a cloud user
  can point it at an Azure/Groq/proxy gateway), `APP_HOST`/`APP_PORT`,
  `DASHBOARD_HOST`/`DASHBOARD_PORT`, `DB_PATH`. Each has a default in
  `config.py` for local use; docker-compose overrides them for the container.

The cloud SDKs are optional dependencies — install the extra for the
provider you want:

```
uv sync --extra openai       # also covers deepseek and grok
uv sync --extra anthropic
```

### Switching to a cloud provider

1. In `config.py`, set the provider (the model defaults from
   `DEFAULT_MODELS`; add `LLM_MODEL_OVERRIDE = "..."` to change it):

   ```python
   # config.py
   LLM_PROVIDER = "openai"
   ```

2. Put the API key in `.env` (copy `.env.example` first):

   ```
   cp .env.example .env
   ```

   ```
   # .env  — secrets only
   OPENAI_API_KEY=sk-...
   ```

   `config.py` calls `load_dotenv()` at startup, so each vendor SDK
   (`OpenAI()`, `Anthropic()`) reads its key straight from the environment.
   `.env` is gitignored; never commit it.

3. Install the SDK and run:

   ```
   uv sync --extra openai
   uv run app.py
   ```

Anthropic, DeepSeek, and Grok work the same way with `ANTHROPIC_API_KEY` /
`DEEPSEEK_API_KEY` / `GROK_API_KEY` (Grok also accepts `XAI_API_KEY`).
DeepSeek and Grok are OpenAI-compatible
(`uv sync --extra openai`), defaulting their base URLs to
`https://api.deepseek.com` and `https://api.x.ai/v1` respectively.

The two-calls-per-submission design and the input caps apply to every
provider. Note that with a cloud provider the draft text is sent to that
vendor; only the default `ollama` path keeps everything on the machine.

## Running with Docker

As an alternative to the local `uv`-based setup above, the whole stack
(Ollama + this app + the dashboard) can run in containers via Docker Compose.

1. Create the data directory and open up its permissions once, so the
   containers (which run as a non-root user) can write to it:

   ```
   mkdir -p data && chmod 777 data
   ```

2. Build and start everything:

   ```
   docker compose up --build
   ```

   The first run pulls the `ollama/ollama` image and the `qwen2.5:3b` model
   into a persistent volume before starting the app and dashboard — this can
   take several minutes depending on connection speed. Subsequent runs reuse
   the cached volume and skip the download.

   To run the containers against a cloud provider instead: set
   `LLM_PROVIDER` in `config.py`, put the API key in `.env`
   (the `app` service loads it via `env_file`), and drop the `ollama` /
   `ollama-pull` services from `docker-compose.yml`. The `environment:`
   block on the `app` service is deployment bindings only (bind address,
   DB path, and the in-cluster Ollama URL).

3. Open the app at http://localhost:7860 and the dashboard at
   http://localhost:7861.

4. Drafts persist to `./data/essays.db` on the host, same as the local setup.

5. Stop everything with `docker compose down` (add `-v` to also delete the
   downloaded model and start fresh next time).

## Input limits

Two soft caps apply per draft: ~1000 words (`config.MAX_WORDS`) and 20
sentences (`config.MAX_SENTENCES`). Both warn but don't block — a longer
draft still runs, but takes longer and risks a larger, slower single batch
call. These caps exist specifically to keep a whole submission small enough
to fit in one questioner call and one checker call. 

Additionally, doing *Write Like a Reader* for anything longer than a couple
paragraphs is over-kill; the idea is to make students **aware** of the concept
so they internalize the process and, hopefully, stop needing the app. 
