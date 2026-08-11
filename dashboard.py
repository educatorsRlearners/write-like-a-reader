"""Standalone dashboard for feedback quality and LLM latency/cost.

A separate process from app.py -- reads the same sqlite database
(`config.DB_PATH`) that app.py/pipeline.py write to, but never creates or
alters schema. Run with `python dashboard.py`.
"""

import config
import gradio as gr
import pandas as pd
import sqlite3

DB_PATH = config.DB_PATH


def _query_df(sql: str, params: tuple = ()) -> pd.DataFrame:
    try:
        with sqlite3.connect(DB_PATH, timeout=5) as conn:
            return pd.read_sql_query(sql, conn, params=params)
    except Exception:
        return pd.DataFrame()


def _feedback_volume_df() -> pd.DataFrame:
    return _query_df("""
        SELECT
            substr(created_at, 1, 10) AS day,
            rating,
            COUNT(*) AS n
        FROM feedback
        GROUP BY day, rating
        ORDER BY day
    """)


def _feedback_rate_df() -> pd.DataFrame:
    return _query_df("""
        SELECT
            substr(created_at, 1, 10) AS day,
            CAST(SUM(CASE WHEN rating = 'good' THEN 1 ELSE 0 END) AS REAL)
                / COUNT(*) AS good_rate
        FROM feedback
        GROUP BY day
        ORDER BY day
    """)


def _llm_avg_duration_df() -> pd.DataFrame:
    return _query_df("""
        SELECT call_type, AVG(duration_ms) AS avg_duration_ms, COUNT(*) AS n
        FROM llm_calls
        GROUP BY call_type
    """)


def _llm_failure_rate_df() -> pd.DataFrame:
    return _query_df("""
        SELECT substr(created_at, 1, 13) AS hour,
               COUNT(*) FILTER (WHERE status = 'failed') AS failed,
               COUNT(*) FILTER (WHERE retries > 0) AS retried,
               COUNT(*) AS total
        FROM llm_calls
        GROUP BY hour
        ORDER BY hour
    """)


def _llm_per_sentence_cost_df() -> pd.DataFrame:
    return _query_df("""
        SELECT call_type, AVG(duration_ms * 1.0 / sentence_count) AS avg_ms_per_sentence
        FROM llm_calls
        GROUP BY call_type
    """)


def _llm_token_usage_df() -> pd.DataFrame:
    return _query_df("""
        SELECT call_type,
               AVG(prompt_tokens) AS avg_prompt_tokens,
               AVG(completion_tokens) AS avg_completion_tokens,
               AVG(prompt_tokens + completion_tokens) AS avg_total_tokens
        FROM llm_calls
        WHERE prompt_tokens IS NOT NULL AND completion_tokens IS NOT NULL
        GROUP BY call_type
    """)


with gr.Blocks(title="Write Like a Reader — Dashboard") as dashboard:
    gr.Markdown("# Write Like a Reader — Dashboard")
    refresh_btn = gr.Button("Refresh")

    with gr.Tab("Feedback Quality"):
        volume_plot = gr.BarPlot(
            x="day", y="n", color="rating", title="Feedback volume by day"
        )
        rate_plot = gr.LinePlot(
            x="day", y="good_rate", title="Good-question rate over time"
        )

    with gr.Tab("LLM Latency"):
        duration_plot = gr.BarPlot(
            x="call_type", y="avg_duration_ms", title="Average duration by call type"
        )
        failure_plot = gr.LinePlot(x="hour", y="failed", title="Failed calls per hour")
        per_sentence_plot = gr.BarPlot(
            x="call_type",
            y="avg_ms_per_sentence",
            title="Average duration per sentence",
        )
        token_plot = gr.BarPlot(
            x="call_type",
            y="avg_total_tokens",
            title="Average total tokens by call type",
        )

    def _refresh_all():
        return (
            _feedback_volume_df(),
            _feedback_rate_df(),
            _llm_avg_duration_df(),
            _llm_failure_rate_df(),
            _llm_per_sentence_cost_df(),
            _llm_token_usage_df(),
        )

    _outputs = [
        volume_plot,
        rate_plot,
        duration_plot,
        failure_plot,
        per_sentence_plot,
        token_plot,
    ]
    dashboard.load(_refresh_all, outputs=_outputs)
    refresh_btn.click(_refresh_all, outputs=_outputs)

if __name__ == "__main__":
    dashboard.launch(
        server_name=config.DASHBOARD_HOST, server_port=config.DASHBOARD_PORT
    )
