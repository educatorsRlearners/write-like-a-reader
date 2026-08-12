FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.12.3 /uv /uvx /usr/local/bin/

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY . .
RUN uv sync --frozen --no-dev

ENV PATH="/app/.venv/bin:$PATH"

# Run as a fixed-UID non-root user rather than root (defense in depth — if
# the Gradio app is ever compromised, the process has no elevated rights).
# uv sync above still runs as root (needs write access to /app); chown
# happens after so the app owns its own files, then we drop privileges.
RUN useradd --uid 1000 --create-home appuser && chown -R appuser:appuser /app
USER appuser

# Neither service binds both ports in a single process — app uses APP_PORT
# (7860), dashboard uses DASHBOARD_PORT (7861). EXPOSE here is documentation
# only; compose's per-service `ports:` mapping is what actually matters.
EXPOSE 7860 7861

CMD ["uv", "run", "app.py"]
