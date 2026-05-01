# ---------------------------------------------------------------------------
# Local dev loop (rebuild/)
#
# The rebuild splits the runtime into two processes you start independently;
# `make dev` only handles the first one.
#
#   1. Docker stack -- `make dev`
#        - mysql  (host :13306 -> container :3306)
#        - redis  (host :16379 -> container :6379)
#        - app    (FastAPI/uvicorn on :8080)
#      Brought up with `docker compose ... up -d --wait`, so the target
#      blocks until every container is healthy. Alembic runs automatically
#      inside the `app` container before uvicorn boots (see
#      `infra/docker-compose.yml`), so you do NOT need to run `make migrate`
#      to get the Docker app working.
#
#   2. Vite dev server -- `npm run dev` (in a separate terminal)
#        - SvelteKit + Vite on :5173, proxying `/api` -> :8080.
#      This is NOT started by `make dev`. After the Docker stack is healthy:
#
#        npm run dev
#
#      Then open http://localhost:5173. Hitting http://localhost:8080
#      directly bypasses the frontend and is only useful for poking at
#      FastAPI routes.
#
# Tear down with `make down` (drops the mysql volume, so all data is wiped).
# Tail container output with `make logs`.
# ---------------------------------------------------------------------------

.PHONY: setup dev dev-rebuild-models migrate lint lint-plans typecheck test-unit test-component test-e2e-smoke test-visual test-visual-update verify-stack verify-migrate build down logs

# One-shot install of backend (uv) and frontend (npm) dependencies.
setup:
	uv sync --frozen --group dev --project backend
	npm ci

# Bring up mysql + redis + app containers and wait for healthchecks.
# `--build` ensures the `app` image is rebuilt when backend or frontend
# source changes -- without it, docker compose silently reuses the cached
# image and you boot stale code (no new routes, no new migrations).
# Reminder: this does NOT start the Vite dev server -- run `npm run dev`
# in a second terminal to serve the SvelteKit frontend on :5173.
dev:
	docker compose -f infra/docker-compose.yml up -d --build --wait --remove-orphans

stop-dev:
	docker compose -f infra/docker-compose.yml down
# Force-recreate the `ollama` container so its entrypoint wrapper re-runs
# the `ollama pull qwen2.5:0.5b` step on next boot. Idempotent: `ollama
# pull` is a no-op on cache hit, so this target is mostly useful when the
# `ollama_models` named volume has been wiped (`make down -v`) or when
# the configured MODELS list in `infra/agent-platform/app/config.py` (or
# its compose-time MODELS env override) has changed and the new tag
# needs to be fetched. Does not touch any other service.
dev-rebuild-models:
	docker compose -f infra/docker-compose.yml up -d --force-recreate --no-deps ollama

# Run Alembic against the host-mapped MySQL container from the host.
# Only needed when iterating on revisions; the Docker `app` container
# migrates itself on boot.
#
# The default `Settings.database_url` (env var `DATABASE_URL`) points at hostname `mysql` (the
# docker compose service name), which only resolves inside the compose
# network. Override here so the host invocation lands on the published
# port (`13306` -> container `3306`, see `infra/docker-compose.yml`).
# A developer can pre-set `DATABASE_URL` in the env to point elsewhere
# (staging, a different local cluster, ...) and the override falls
# through.
migrate:
	cd backend && DATABASE_URL=$${DATABASE_URL:-mysql+asyncmy://rebuild:rebuild@127.0.0.1:13306/rebuild?charset=utf8mb4} uv run --project . alembic upgrade head

# Lint backend (ruff) and frontend (eslint + prettier + custom grep).
#
# The `pydantic-ai` grep gate enforces that the dev-only agent platform's
# pydantic-ai dependency does not leak into the runtime backend. The
# agent platform lives under `infra/agent-platform/` (separate Python
# project with its own pyproject + lock); the runtime image must never
# pick up pydantic-ai or its transitives. See
# `rebuild/docs/plans/feature-llm-models.md` § Deliverables and
# § pyproject.toml for the rationale; this is the first backend custom
# grep gate (mirrors the frontend `lint:grep` pattern from m0).
lint: lint-plans
	uv run --project backend ruff check backend
	uv run --project backend ruff format --check backend
	@! grep -RInE 'pydantic[-_]ai' backend || (echo "ERROR: pydantic-ai must not appear under rebuild/backend/ -- see rebuild/docs/plans/feature-llm-models.md" && exit 1)
	npm run -s lint

# Every milestone and feature plan under `docs/plans/` MUST have a
# `## User journeys` section and the mandatory three-layer visual-QA
# acceptance criterion. The section drives Layer A (baselines), Layer B
# (geometric invariants), and Layer C (impeccable design review) per
# `docs/best-practises/visual-qa-best-practises.md`; without it the
# verifier has nothing to check against.
#
# Milestones that ship no product UI opt out by writing the literal
# phrase `_No product UI in this milestone._` as the section's sole
# content — the second grep below enforces that every section is either
# populated (has a row with "Layer A") or explicitly marked n/a.
#
# See `docs/plans/PLAN-TEMPLATE.md` for the canonical shape.
lint-plans:
	@set -e ; \
	  for f in docs/plans/m[0-9]*.md docs/plans/feature-*.md ; do \
	    grep -q '^## User journeys' "$$f" || { \
	      echo "ERROR: $$f is missing a '## User journeys' section." ; \
	      echo "       See docs/plans/PLAN-TEMPLATE.md and docs/best-practises/visual-qa-best-practises.md." ; \
	      exit 1 ; \
	    } ; \
	    grep -qE '(Layer A|No product UI in this milestone\.)' "$$f" || { \
	      echo "ERROR: $$f has a '## User journeys' section but no journey rows and no explicit n/a marker." ; \
	      echo "       Populate the table (columns: Journey | Layer A | Layer B | Layer C) or write" ; \
	      echo "       '_No product UI in this milestone._' as the section's sole content." ; \
	      exit 1 ; \
	    } ; \
	    grep -q 'Three-layer visual QA' "$$f" || { \
	      echo "ERROR: $$f is missing the mandatory 'Three-layer visual QA' acceptance-criteria row." ; \
	      echo "       Copy the row verbatim from docs/plans/PLAN-TEMPLATE.md § Mandatory acceptance criterion." ; \
	      exit 1 ; \
	    } ; \
	  done ; \
	  echo "lint-plans: all plans have § User journeys and the three-layer acceptance criterion"

# Static typechecks: mypy for backend, svelte-check for frontend.
typecheck:
	uv run --project backend mypy backend/app
	npm run -s check

# Backend pytest + frontend vitest unit suites.
test-unit:
	uv run --project backend pytest backend/tests
	npm run -s test:unit

# Playwright component tests (Svelte components mounted in isolation).
# This is the primary home for Layer B geometric-invariant specs per
# `rebuild/docs/best-practises/visual-qa-best-practises.md` — component-
# level overlap / containment / clipping invariants live in
# `frontend/tests/component/*-geometry.spec.ts` so they run hermetically
# without needing the backend + Vite dev server.
test-component:
	npm run -s test:ct

# Playwright @smoke-tagged end-to-end suite. Requires the Docker stack
# (`make dev`) AND the Vite dev server (`npm run dev`) to be running.
test-e2e-smoke:
	npm run -s test:e2e:smoke

# Playwright @visual-tagged baselines (pixel-diff via `toHaveScreenshot`).
# Matches every milestone's `@visual-m{n}` tag. Requires the Docker stack
# + Vite dev server AND the Linux container image the baselines were
# captured on (macOS font-hinting drift will inflate diffs into the tens
# of thousands of pixels — run inside the CI image via `docker compose
# run ... make test-visual` for a clean local result).
#
# See `rebuild/docs/best-practises/visual-qa-best-practises.md` § Layer A
# for capture workflow and `rebuild/docs/plans/m6-hardening.md` § Visual-
# regression CI for the Buildkite wiring.
test-visual:
	npm run -s test:visual

# Manual-only: refresh the pixel-diff baselines. NEVER run by CI. Use
# the Buildkite `block: "Refresh visual baselines"` step documented in
# `rebuild/docs/plans/m6-hardening.md` § Baseline refresh, or run
# locally inside the CI Linux image to avoid font drift. Regenerated
# PNGs are committed via Git LFS and reviewed in GitHub's image-diff
# view; baselines never auto-merge.
test-visual-update:
	npm run -s test:visual:update

# Cold-build the docker image, bring up mysql + redis + app, hit the
# canonical health + bootstrap routes, confirm the DB is at the expected
# alembic head, and tear down. This is the "the stack actually boots
# clean from cold" gate the verifier and milestone acceptance criteria
# rely on; it catches Dockerfile regressions, missing build-time env
# vars, and broken migrations that the lint / typecheck / unit / e2e
# gates can't see.
#
# COLD-START BUDGET: with the agent-platform / ollama services now in the
# compose stack (see `feature-llm-models.md`), a fresh runner that has
# no `ollama_models` volume cached pays a one-time `ollama pull
# qwen2.5:0.5b` cost (~400 MB) before the ollama container reports
# healthy, which gates agent-platform startup, which gates the rebuild's
# app startup. Wall-clock budget grows from ~30 s to ~3-5 minutes on
# that first run; subsequent runs (cached docker layer + populated
# `ollama_models` volume) stay at the existing budget. If a future
# investigation flags "verify-stack got slower", check whether the
# ollama_models volume was dropped (`make down` does drop it) — that's
# the single most likely cause.
#
# DESTRUCTIVE: tears down the rebuild_* compose stack and drops the
# mysql volume on entry AND on exit (success or failure). Don't run
# while you have work-in-progress data in the dev MySQL.
verify-stack:
	@bash -c 'set -eu ; \
	  trap "docker compose -f infra/docker-compose.yml down -v --remove-orphans >/dev/null 2>&1 || true" EXIT ; \
	  docker compose -f infra/docker-compose.yml down -v --remove-orphans >/dev/null 2>&1 || true ; \
	  echo "==> docker compose up --build --wait" ; \
	  docker compose -f infra/docker-compose.yml up -d --build --wait ; \
	  echo "==> GET /healthz" ; curl -fsS http://localhost:8080/healthz ; echo ; \
	  echo "==> GET /readyz"  ; curl -fsS http://localhost:8080/readyz  ; echo ; \
	  echo "==> GET /api/me (trusted-header bootstrap)" ; \
	  curl -fsS -H "X-Forwarded-Email: verifier@canva.com" http://localhost:8080/api/me ; echo ; \
	  echo "==> GET /api/models (must return non-empty)" ; \
	  curl -fsS -H "X-Forwarded-Email: verifier@canva.com" http://localhost:8080/api/models \
	    | python3 -c "import json,sys; d=json.load(sys.stdin); assert d.get(\"items\"), \"no models returned\"; print(\"models: \" + \",\".join(m[\"id\"] for m in d[\"items\"]))" ; \
	  echo "==> alembic head" ; \
	  docker exec rebuild_mysql mysql -urebuild -prebuild rebuild -sNe "SELECT version_num FROM alembic_version" 2>/dev/null ; \
	  echo "verify-stack OK"'

# Bring up only the mysql container, run `make migrate` against it from
# the host (exercises the documented host alembic flow), and confirm the
# DB lands at head. Catches alembic.ini path bugs and DATABASE_URL
# defaults that don't resolve from the host.
#
# DESTRUCTIVE: tears down rebuild_mysql and drops its volume on entry
# AND on exit so the host migration starts against an empty schema.
verify-migrate:
	@bash -c 'set -eu ; \
	  trap "docker compose -f infra/docker-compose.yml down -v --remove-orphans >/dev/null 2>&1 || true" EXIT ; \
	  docker compose -f infra/docker-compose.yml down -v --remove-orphans >/dev/null 2>&1 || true ; \
	  echo "==> docker compose up mysql --wait" ; \
	  docker compose -f infra/docker-compose.yml up -d mysql --wait ; \
	  echo "==> make migrate" ; \
	  $(MAKE) -s migrate ; \
	  echo "==> alembic head" ; \
	  docker exec rebuild_mysql mysql -urebuild -prebuild rebuild -sNe "SELECT version_num FROM alembic_version" 2>/dev/null ; \
	  echo "verify-migrate OK"'

# Build the production app image (used by CI and prod deploy, not by
# `make dev` -- which builds via docker compose).
build:
	docker build -t open-webui-rebuild:dev .

# Stop the Docker stack and DROP the mysql volume. Destructive.
down:
	docker compose -f infra/docker-compose.yml down -v

# Tail the last 100 lines of every Docker stack container, follow new output.
logs:
	docker compose -f infra/docker-compose.yml logs -f --tail=100
