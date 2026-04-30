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

.PHONY: setup dev migrate lint typecheck test-unit test-component test-e2e-smoke build down logs

# One-shot install of backend (uv) and frontend (npm) dependencies.
setup:
	uv sync --frozen --group dev --project backend
	npm ci

# Bring up mysql + redis + app containers and wait for healthchecks.
# Reminder: this does NOT start the Vite dev server -- run `npm run dev`
# in a second terminal to serve the SvelteKit frontend on :5173.
dev:
	docker compose -f infra/docker-compose.yml up -d --wait

# Run Alembic against the configured DATABASE_URL from the host. Only
# needed when iterating on revisions; the Docker `app` container migrates
# itself on boot.
migrate:
	cd backend && uv run --project . alembic upgrade head

# Lint backend (ruff) and frontend (eslint + prettier + custom grep).
lint:
	uv run --project backend ruff check backend
	uv run --project backend ruff format --check backend
	npm run -s lint

# Static typechecks: mypy for backend, svelte-check for frontend.
typecheck:
	uv run --project backend mypy backend/app
	npm run -s check

# Backend pytest + frontend vitest unit suites.
test-unit:
	uv run --project backend pytest backend/tests
	npm run -s test:unit

# Playwright component tests (Svelte components mounted in isolation).
test-component:
	npm run -s test:ct

# Playwright @smoke-tagged end-to-end suite. Requires the Docker stack
# (`make dev`) AND the Vite dev server (`npm run dev`) to be running.
test-e2e-smoke:
	npm run -s test:e2e:smoke

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
