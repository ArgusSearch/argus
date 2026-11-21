# The only commands anyone needs. Everything runs through uv, which installs the locked environment on demand.
SEED ?= 7
PORT ?= 8000
# SCENARIO picks the world for world, demo and api: quiet, s1, s2, s3, s4 or s5.
SCENARIO ?= s1
RECORDED := quiet s2 s3 s4 s5
REPLAY ?= fixtures$(if $(filter s1,$(SCENARIO)),,/$(SCENARIO))
BENCH_OUT ?= runs/bench
S1_OUT ?= runs
AGENT_EVAL_OUT ?= runs/agent-eval
CONTRACTS_BASE := 2c36e8204f3082aa1a9ddfd613ab545247fdc5ef

.PHONY: setup check lint format typecheck test test-fast contracts contracts-check contracts-frozen web s1 bench agent-eval agent-eval-live world demo api fixtures clean

setup:            ## install the locked environment
	uv sync

check: lint typecheck contracts-check contracts-frozen web test   ## offline release checks

lint:
	uv run ruff check .
	uv run ruff format --check .

format:
	uv run ruff check --fix .
	uv run ruff format .

typecheck:
	uv run mypy

test: agent-eval
	uv run pytest --ignore=tests/agent_evals

test-fast:        ## unit tests only, skips the end-to-end scenario runs
	uv run pytest -m "not e2e"

contracts:        ## regenerate contracts/ from src/argus/contracts
	uv run python -m argus.contracts.export

contracts-check:
	uv run python -m argus.contracts.export --check

contracts-frozen:  ## ensure all six versioned contracts still match the frozen baseline
	git diff --exit-code $(CONTRACTS_BASE) -- contracts/ src/argus/contracts/

web:              ## Mission Control: install its locked dependencies if missing, test, typecheck and build web/dist
	@[ -d web/node_modules ] || npm --prefix web ci
	npm --prefix web test
	npm --prefix web run build

s1:               ## S1 end to end: simulate PayCo outage + release red herring, run Argus, grade against truth
	uv run argus-bench s1 --seed $(SEED) --runs-dir "$(S1_OUT)"

bench:            ## the scorecard: every scenario x 3 seeds, Argus against the threshold baseline
	uv run argus-bench run --out "$(BENCH_OUT)"
	uv run python -m scripts.agent_eval.bench_gate "$(BENCH_OUT)"

agent-eval:        ## run deterministic agent release evals with provider access disabled
	@status=0; ARGUS_DISABLE_PROVIDER=1 uv run pytest tests/agent_evals --junitxml="$(AGENT_EVAL_OUT)/pytest.xml" || status=$$?; \
	uv run python -m scripts.agent_eval.offline_report "$(AGENT_EVAL_OUT)/pytest.xml" --out "$(AGENT_EVAL_OUT)/scorecard.json" || exit $$?; \
	exit $$status

agent-eval-live:   ## score retained paid trials from TRIALS and write the live stage decision
	@test -n "$(TRIALS)" || { printf '%s\n' 'Set TRIALS to the paid qualification archive.' >&2; exit 2; }
	uv run python -m scripts.agent_eval.qualify "$(TRIALS)" --out "$(AGENT_EVAL_OUT)/qualification.json" $(if $(TEXT_REVIEW),--text-review "$(TEXT_REVIEW)")

world:            ## generate a $(SCENARIO) world into runs/$(SCENARIO)-$(SEED)
	uv run mockmart generate --scenario $(SCENARIO) --seed $(SEED) --out runs/$(SCENARIO)-$(SEED)

api:              ## API with SSE replaying a recorded run: fixtures/ (S1), or fixtures/$(SCENARIO) for the others
	uv run argus api --port $(PORT) --replay $(REPLAY)

demo: world       ## API that runs Argus live over a fresh $(SCENARIO) world and streams events
	uv run argus api --port $(PORT) --world runs/$(SCENARIO)-$(SEED)/world.duckdb

fixtures:         ## re-record fixtures/ (S1, seed 1) and fixtures/<scenario> for quiet, s2, s3, s4 and s5
	uv run argus-bench s1 --seed 1 --record fixtures
	for s in $(RECORDED); do uv run argus-bench record $$s --seed 1 --out fixtures/$$s || exit 1; done

clean:
	rm -rf runs state .pytest_cache .ruff_cache .mypy_cache
