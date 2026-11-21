# The only commands anyone needs. Everything runs through uv, which installs the locked environment on demand.
SEED ?= 7
PORT ?= 8000

.PHONY: setup check lint format typecheck test test-fast contracts contracts-check s1 world demo api fixtures clean

setup:            ## install the locked environment
	uv sync

check: lint typecheck contracts-check test   ## everything CI runs

lint:
	uv run ruff check .
	uv run ruff format --check .

format:
	uv run ruff check --fix .
	uv run ruff format .

typecheck:
	uv run mypy

test:
	uv run pytest

test-fast:        ## unit tests only, skips the end-to-end scenario runs
	uv run pytest -m "not e2e"

contracts:        ## regenerate contracts/ from src/argus/contracts
	uv run python -m argus.contracts.export

contracts-check:
	uv run python -m argus.contracts.export --check

s1:               ## S1 end to end: simulate PayCo outage + release red herring, run Argus, grade against truth
	uv run argus-bench s1 --seed $(SEED)

world:            ## generate an S1 world into runs/s1-$(SEED)
	uv run mockmart generate --scenario s1 --seed $(SEED) --out runs/s1-$(SEED)

api:              ## API with SSE replaying fixtures/events.jsonl
	uv run argus api --port $(PORT)

demo: world       ## API that runs Argus live over the S1 world and streams events
	uv run argus api --port $(PORT) --world runs/s1-$(SEED)/world.duckdb

fixtures:         ## re-record fixtures/ from an S1 run (graph.json, events.jsonl, findings.json, ...)
	uv run argus-bench s1 --seed 1 --record fixtures

clean:
	rm -rf runs state .pytest_cache .ruff_cache .mypy_cache
