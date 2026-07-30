import tempfile

import gradio as gr

import highlight
import pipeline
from config import MAX_WORDS

EXAMPLE_DRAFT = (
    "Social media has changed the way people communicate. Many students use it "
    "every day. Some teachers think it is a distraction. The school board is "
    "considering a new policy. This would help students focus better."
)


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


def _status_notice(result: pipeline.PipelineResult) -> str:
    n = len(result.sentences)
    if n == 0:
        return ""
    if len(result.failed_rounds) == n:
        return (
            "⚠️ Could not get feedback for any sentence — the feedback backend "
            "was unreachable. Check that `HF_TOKEN` is set and the model is "
            "available, then try again."
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

    notice = _word_count_notice(draft_text)

    def on_progress(i, n):
        progress((i, n), desc=f"Reading sentence {i + 1} of {n}")

    try:
        result = pipeline.run(draft_text, on_progress=on_progress)
    except Exception as exc:
        raise gr.Error(f"Feedback run failed unexpectedly: {exc}") from exc

    status = _status_notice(result)
    full_notice = "\n\n".join(part for part in (notice, status) if part)
    chunks = highlight.to_highlighted_text(result)
    chunk_map = highlight.chunk_sentence_indices(result)
    return (result, chunk_map), chunks, full_notice, ""


def on_select(state, evt: gr.SelectData):
    result, chunk_map = state
    if result is None or evt.index is None:
        return ""
    idx = evt.index
    if isinstance(idx, (tuple, list)):
        idx = idx[0]
    if idx >= len(chunk_map):
        return ""
    sentence_index = chunk_map[idx]
    if sentence_index is None:
        return "*(no question here)*"
    annotation = next(
        (a for a in result.annotations if a.sentence_index == sentence_index), None
    )
    if annotation is None:
        return "*(this sentence has no unanswered questions)*"
    lines = [
        f"- **{q.category.value.title()}**: {q.text}" for q in annotation.questions
    ]
    return "\n".join(lines)


def build_download(state):
    result, _chunk_map = state
    if result is None:
        raise gr.Error("Get feedback on a draft first.")
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
        "Paste or upload your draft. An AI reader will go through it sentence by "
        "sentence and flag the questions it still has — the same way a human "
        "peer reviewer would. **It won't fix anything for you** — the point is "
        "for you to answer those questions yourself in your revision."
    )
    gr.Markdown(
        "**Legend:** "
        f"<span style='color:{highlight.COLOR_MAP[highlight.DETAIL]}'>■ detail (who/what/when/where/how)</span> &nbsp; "
        f"<span style='color:{highlight.COLOR_MAP[highlight.REASON]}'>■ reason (why)</span> &nbsp; "
        f"<span style='color:{highlight.COLOR_MAP[highlight.MIXED]}'>■ both</span>"
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
    )
    detail_panel = gr.Markdown(label="Selected sentence's unanswered questions")
    download_btn = gr.Button("Download annotated draft")
    download_file = gr.File(label="Download", visible=True)

    result_state = gr.State((None, None))

    file_upload.upload(load_txt, inputs=file_upload, outputs=draft_box)
    example_btn.click(lambda: EXAMPLE_DRAFT, outputs=draft_box)

    feedback_btn.click(
        get_feedback,
        inputs=draft_box,
        outputs=[result_state, highlighted, notice_md, detail_panel],
    )

    highlighted.select(on_select, inputs=result_state, outputs=detail_panel)
    download_btn.click(build_download, inputs=result_state, outputs=download_file)

demo.queue()

if __name__ == "__main__":
    demo.launch()
