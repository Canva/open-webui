
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
.PHONY: build lint lint-frontend lint-backend format format-frontend format-backend

IMAGE_NAME ?= open-webui
IMAGE_TAG  ?= latest

setup:
	uv sync --all-groups
	npm ci

build:
	docker build -t $(IMAGE_NAME):$(IMAGE_TAG) .

lint: format lint-frontend lint-backend

format: format-frontend format-backend

fix: format-backend format-frontend lint-backend lint-frontend
format-frontend:
	npx prettier --plugin-search-dir --write "**/*.{js,ts,svelte,css,md,html,json}"

format-backend:
	ruff format . --exclude .venv --exclude venv

lint-frontend:
	npx eslint . --fix

lint-backend:
	ruff check --fix .

