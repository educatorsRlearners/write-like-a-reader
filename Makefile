# Targets assume a POSIX shell (macOS, Linux, or WSL/Git Bash on Windows).
# On native Windows without one of those, use `docker compose` directly
# instead of `make` (see the "Running with Docker" section in README.md).

# Resolved once, at parse time: use `uv` from PATH if it's already there,
# otherwise fall back to the path the official installer (see ensure-uv)
# puts it in, so later targets find it even if PATH hasn't been refreshed
# in this shell yet.
UV := $(shell command -v uv 2>/dev/null || echo $$HOME/.local/bin/uv)

.PHONY: help run sync test app dashboard data-dir ensure-uv ensure-ollama docker-up docker-down docker-down-clean clean

run: data-dir sync ensure-ollama app ## Install everything and launch the app (default)

help: ## Show this help
	@echo "Usage: make <target>"
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*## ' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*## "}; {printf "  %-18s %s\n", $$1, $$2}'

ensure-uv: ## Install uv (the Python package manager) if missing
	@command -v uv >/dev/null 2>&1 || [ -x "$(UV)" ] || { \
		echo "uv not found -- installing..."; \
		curl -LsSf https://astral.sh/uv/install.sh | sh; \
	}

sync: ensure-uv ## Install/sync dependencies (uv sync)
	$(UV) sync

test: ensure-uv ## Run the test suite (uv run pytest)
	$(UV) run pytest

app: ensure-uv ## Launch the main Gradio app (port 7860)
	$(UV) run app.py

dashboard: ensure-uv ## Launch the feedback/latency dashboard (port 7861)
	$(UV) run dashboard.py

data-dir: ## Create ./data and open its permissions for the Docker containers
	mkdir -p data && chmod 777 data

ensure-ollama: sync ## Install Ollama if missing, start it, and pull the model from config.py
	@CFG=$$($(UV) run python -c "import config; print(config.LLM_PROVIDER, config.LLM_MODEL, config.LLM_BASE_URL)"); \
	set -- $$CFG; PROVIDER=$$1; MODEL=$$2; URL=$$3; \
	if [ "$$PROVIDER" != "ollama" ]; then \
		echo "LLM_PROVIDER=$$PROVIDER -- skipping Ollama setup."; \
		exit 0; \
	fi; \
	command -v ollama >/dev/null 2>&1 || { \
		echo "Ollama not found -- installing..."; \
		case "$$(uname -s)" in \
			Darwin) \
				if command -v brew >/dev/null 2>&1; then \
					brew install ollama; \
				else \
					curl -fsSL https://ollama.com/install.sh | sh; \
				fi ;; \
			Linux) \
				curl -fsSL https://ollama.com/install.sh | sh ;; \
			*) \
				echo "Don't know how to install Ollama automatically on $$(uname -s)."; \
				echo "Install it manually from https://ollama.com/download, or run"; \
				echo "'make docker-up' instead, which runs Ollama in a container."; \
				exit 1 ;; \
		esac; \
	}; \
	curl -sf "$$URL" >/dev/null 2>&1 || { \
		echo "Starting Ollama service..."; \
		nohup ollama serve >/tmp/ollama-serve.log 2>&1 & \
		for i in 1 2 3 4 5 6 7 8 9 10; do \
			curl -sf "$$URL" >/dev/null 2>&1 && break; \
			sleep 1; \
		done; \
	}; \
	echo "Pulling model $$MODEL (skips if already present)..."; \
	ollama pull "$$MODEL"

docker-up: ## Build and start Ollama + app + dashboard via Docker Compose
	docker compose up --build

docker-down: ## Stop the Docker Compose stack
	docker compose down

docker-down-clean: ## Stop the stack and delete the downloaded Ollama model volume
	docker compose down -v

clean: ## Remove cached bytecode and pytest cache
	rm -rf __pycache__ tests/__pycache__ .pytest_cache

.DEFAULT_GOAL := run
