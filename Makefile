# Convenience targets (run on the RTX 3090 machine). Everything also works with plain docker compose commands.
ROLE ?= policy_guard
MODELS ?= qwen-8b
BRIEF ?= evals/briefs/invoice_templates.json
RUN ?=

up:
	docker compose up -d --build
	@echo "Open http://localhost:8000"

logs:
	docker compose logs -f app

test:
	docker compose run --rm --no-deps app python -m pytest -q

# Time intake -> desk-gate verdict on the GPU (demo-fast) and record peak VRAM
demo:
	docker compose exec app python -m app.cli run --brief $(BRIEF)

# The recorded STOP run (thresholds are in config/gate_definitions.yaml, committed before running)
stop-run:
	docker compose exec app python -m app.cli run --brief evals/briefs/crowded_todo_app.json --decide STOP

publish:
	docker compose exec app python -m app.cli publish $(RUN)

eval:
	docker compose exec app python -m evals.runner --role $(ROLE) --models $(MODELS)

eval-gate:
	docker compose exec -e SEARCH_MODE=fixtures app python -m evals.runner --role desk_gate --profiles demo-fast,quality

down:
	docker compose down
