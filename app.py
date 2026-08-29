import logging
import tempfile

import gradio as gr

import highlight
import llm_providers
import pipeline
import sentence_split
import storage
from config import (
    APP_HOST,
    APP_PORT,
    EXAMPLE_DRAFT,
    LLM_PROVIDER,
    MAX_SENTENCES,
    MAX_WORDS,
)

logger = logging.getLogger(__name__)


def load_txt(file_path: str | None):
    if not file_path:
        return gr.update()
    with open(file_path, encoding="utf-8") as f:
        return f.read()


def _word_count_notice(text: str) -> str:
    word_count = len(text.split())
    if word_count > MAX_WORDS:
        return (
            f"⚠️ This draft is {word_count} words, over the ~{MAX_WORDS}-word soft "
            "cap. You can still get feedback, but a draft this long can take "
            "several minutes and may hit rate limits."
        )
    return ""


def _sentence_count_notice(sentences: list) -> str:
    n = len(sentences)
    if n > MAX_SENTENCES:
        return (
            f"⚠️ This draft has {n} sentences, over the ~{MAX_SENTENCES}-sentence "
            "soft cap. You can still get feedback, but a draft this long can take "
            "longer and may hit rate limits."
        )
    return ""


def _status_notice(result: pipeline.PipelineResult) -> str:
    n = len(result.sentences)
    if n == 0:
        return ""
    if len(result.failed_rounds) == n:
        if LLM_PROVIDER == "ollama":
            fix = (
                "Check that Ollama is running (`ollama serve`) and the model has "
                "been pulled, then try again."
            )
        elif LLM_PROVIDER not in llm_providers.PROVIDER_API_KEY_ENV:
            fix = (
                f"LLM_PROVIDER={LLM_PROVIDER!r} is not a recognized backend "
                "(expected: ollama, openai, anthropic, deepseek)."
            )
        else:
            key_var = llm_providers.PROVIDER_API_KEY_ENV[LLM_PROVIDER]
            fix = (
                f"Check that {key_var} is set in your .env and that LLM_MODEL "
                f"in config.py is valid for the '{LLM_PROVIDER}' provider, "
                "then try again."
            )
        return (
            "⚠️ Could not get feedback for any sentence — the feedback backend "
            f"was unreachable. {fix}"
        )
    if 0 in result.failed_rounds:
        return (
            "⚠️ Feedback may be incomplete — the very first sentence's round "
            "failed, so its questions weren't generated."
        )
    if result.failed_rounds:
        return (
            f"Note: feedback for {len(result.failed_rounds)} sentence(s) could "
            "not be generated and was skipped."
        )
    return ""


def get_feedback(draft_text: str, progress=gr.Progress()):
    if not draft_text or not draft_text.strip():
        raise gr.Error("Please enter or upload a draft first.")

    essay_id = None
    try:
        essay_id = storage.save_essay(draft_text)
    except Exception:
        logger.warning("Failed to save essay to storage", exc_info=True)

    word_notice = _word_count_notice(draft_text)
    sentence_notice = _sentence_count_notice(sentence_split.split_sentences(draft_text))

    def on_progress(step, total):
        desc = "Reading the essay..." if step == 0 else "Checking answers..."
        progress((step, total), desc=desc)

    try:
        result = pipeline.run(draft_text, essay_id=essay_id, on_progress=on_progress)
    except Exception as exc:
        logger.exception("Feedback run failed unexpectedly")
        raise gr.Error(
            f"Feedback run failed unexpectedly ({type(exc).__name__}). "
            "See the server logs for details."
        ) from exc

    if essay_id is not None:
        try:
            storage.save_questions(essay_id, result.question_log)
        except Exception:
            logger.warning("Failed to save questions to storage", exc_info=True)

    status = _status_notice(result)
    full_notice = "\n\n".join(
        part for part in (word_notice, sentence_notice, status) if part
    )
    chunks = highlight.to_highlighted_text(result)
    chunk_map = highlight.chunk_sentence_indices(result)
    download_path = _write_annotated_draft(result)
    return (result, chunk_map), chunks, full_notice, "", None, download_path


def on_select(state, evt: gr.SelectData):
    result, chunk_map = state
    if result is None or evt.index is None:
        return "", None
    idx = evt.index
    if isinstance(idx, (tuple, list)):
        idx = idx[0]
    if idx >= len(chunk_map):
        return "", None
    sentence_index = chunk_map[idx]
    if sentence_index is None:
        return "*(no question here)*", None
    annotation = next(
        (a for a in result.annotations if a.sentence_index == sentence_index), None
    )
    if annotation is None:
        return "*(this sentence has no unanswered questions)*", None
    lines = [f"- {q.text}" for q in annotation.questions]
    selection = (
        (result.essay_id, sentence_index) if result.essay_id is not None else None
    )
    return "\n".join(lines), selection


def _rate(selection, rating: str):
    if selection is None:
        return gr.update(value="*(select a flagged sentence first)*")
    essay_id, sentence_index = selection
    try:
        storage.save_feedback(essay_id, sentence_index, rating)
    except Exception:
        logger.warning("Failed to save feedback", exc_info=True)
        return gr.update(value="*(couldn't save — try again)*")
    return gr.update(value="Thanks!" if rating == "good" else "Noted.")


def _write_annotated_draft(result: pipeline.PipelineResult) -> str:
    text = highlight.annotated_draft_text(result)
    tmp = tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".txt",
        delete=False,
        encoding="utf-8",
        prefix="annotated_draft_",
    )
    tmp.write(text)
    tmp.close()
    return tmp.name


with gr.Blocks(title="Write Like a Reader") as demo:
    gr.Markdown(
        "# Write Like a Reader\n"
        "Paste or upload a paragraph or two of your writing. An AI reader will "
        "go through it sentence by sentence and flag the questions it still "
        "has — the same way a human peer reviewer would. **It won't fix "
        "anything for you** — the point is for you to answer those questions "
        "yourself in your revision."
    )
    gr.Markdown(
        "*We save the drafts you submit here in order to improve this "
        "service going forward. Don't include personal information you "
        "wouldn't want retained.*"
    )

    with gr.Row():
        draft_box = gr.Textbox(
            label="Your draft", lines=15, placeholder="Paste your draft here..."
        )
        with gr.Column(scale=0, min_width=200):
            file_upload = gr.File(label="...or upload a .txt file", file_types=[".txt"])
            example_btn = gr.Button("Load example draft")

    feedback_btn = gr.Button("Get Feedback", variant="primary")
    notice_md = gr.Markdown()

    highlighted = gr.HighlightedText(
        label="Annotated draft",
        color_map=highlight.COLOR_MAP,
        show_legend=False,
        show_inline_category=False,
    )
    detail_panel = gr.Markdown(label="Selected sentence's unanswered questions")
    with gr.Row():
        good_btn = gr.Button("👍 Good questions", size="sm", scale=0)
        bad_btn = gr.Button("👎 Bad questions", size="sm", scale=0)
    feedback_status_md = gr.Markdown(scale=0)
    download_btn = gr.DownloadButton("Download annotated draft")

    result_state = gr.State((None, None))
    current_selection_state = gr.State(None)  # (essay_id, sentence_index) | None

    file_upload.upload(load_txt, inputs=file_upload, outputs=draft_box)
    example_btn.click(lambda: EXAMPLE_DRAFT, outputs=draft_box)

    feedback_btn.click(
        get_feedback,
        inputs=draft_box,
        outputs=[
            result_state,
            highlighted,
            notice_md,
            detail_panel,
            current_selection_state,
            download_btn,
        ],
    )

    highlighted.select(
        on_select,
        inputs=result_state,
        outputs=[detail_panel, current_selection_state],
    )

    good_btn.click(
        lambda selection: _rate(selection, "good"),
        inputs=[current_selection_state],
        outputs=[feedback_status_md],
    )
    bad_btn.click(
        lambda selection: _rate(selection, "bad"),
        inputs=[current_selection_state],
        outputs=[feedback_status_md],
    )

demo.queue()

if __name__ == "__main__":
    demo.launch(server_name=APP_HOST, server_port=APP_PORT)
