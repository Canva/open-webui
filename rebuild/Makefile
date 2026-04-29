.PHONY: setup dev migrate lint typecheck test-unit test-component test-e2e-smoke build down logs

setup:
	uv sync --frozen --group dev --project backend
	npm ci

dev:
	docker compose -f infra/docker-compose.yml up -d --wait

migrate:
	cd backend && uv run --project . alembic upgrade head

lint:
	uv run --project backend ruff check backend
	uv run --project backend ruff format --check backend
	npm run -s lint

typecheck:
	uv run --project backend mypy backend/app
	npm run -s check

test-unit:
	uv run --project backend pytest backend/tests
	npm run -s test:unit

test-component:
	npm run -s test:ct

test-e2e-smoke:
	npm run -s test:e2e:smoke

build:
	docker build -t open-webui-rebuild:dev .

down:
	docker compose -f infra/docker-compose.yml down -v

logs:
	docker compose -f infra/docker-compose.yml logs -f --tail=100
