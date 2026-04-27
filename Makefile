
ifneq ($(shell which docker-compose 2>/dev/null),)
    DOCKER_COMPOSE := docker-compose
else
    DOCKER_COMPOSE := docker compose
endif

install:
	$(DOCKER_COMPOSE) up -d

remove:
	@chmod +x confirm_remove.sh
	@./confirm_remove.sh

start:
	$(DOCKER_COMPOSE) start
startAndBuild:
	$(DOCKER_COMPOSE) up -d --build

stop:
	$(DOCKER_COMPOSE) stop

update:
	# Calls the LLM update script
	chmod +x update_ollama_models.sh
	@./update_ollama_models.sh
	@git pull
	$(DOCKER_COMPOSE) down
	# Make sure the ollama-webui container is stopped before rebuilding
	@docker stop open-webui || true
	$(DOCKER_COMPOSE) up --build -d
	$(DOCKER_COMPOSE) start

###############################################################################
# Canva targets
###############################################################################
.PHONY: build lint lint-frontend lint-backend format format-frontend format-backend setup test-mysql dev-backend dev-frontend

NVM_DIR    ?= $(HOME)/.nvm
NVM_NODE   := $(firstword $(wildcard $(NVM_DIR)/versions/node/v22.*/bin))
NODE_PATH  := $(if $(NVM_NODE),$(NVM_NODE),)
NPM        := $(if $(NODE_PATH),PATH="$(NODE_PATH):$$PATH" npm,npm)
NPX        := $(if $(NODE_PATH),PATH="$(NODE_PATH):$$PATH" npx,npx)

IMAGE_NAME ?= open-webui
IMAGE_TAG  ?= latest

setup:
	uv sync --all-groups
	$(NPM) ci

dev-backend:
	@if [ -f local-compose.env ]; then echo "Loading env from local-compose.env"; \
	else echo "Note: local-compose.env not found - relying on current shell env. Copy local-compose.env.example to enable local-compose defaults."; fi
	cd backend && export PORT=5080 && \
		uv run $$([ -f ../local-compose.env ] && echo --env-file ../local-compose.env) ./dev.sh

dev-frontend:
	$(NPM) run dev

build:
	docker build -t $(IMAGE_NAME):$(IMAGE_TAG) .

lint: format lint-frontend lint-backend

format: format-frontend format-backend

format-frontend:
	$(NPX) prettier --write "**/*.{js,ts,svelte,css,md,html,json}"

format-backend:
	uv run ruff format . --exclude .venv --exclude venv

lint-frontend:
	$(NPX) eslint . --fix

lint-backend:
	uv run ruff check --fix .

test-mysql:
	cd backend && PYTHONPATH=. uv run pytest \
		open_webui/test/test_mysql_migrations.py \
		open_webui/test/test_mysql_migration_chain.py \
		open_webui/test/test_mysql_queries.py \
		-v

