
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

NVM_DIR    ?= $(HOME)/.nvm
NVM_NODE   := $(wildcard $(NVM_DIR)/versions/node/v22.*/bin)
NODE_PATH  := $(if $(NVM_NODE),$(NVM_NODE),)
NPM        := $(if $(NODE_PATH),PATH="$(NODE_PATH):$$PATH" npm,npm)
NPX        := $(if $(NODE_PATH),PATH="$(NODE_PATH):$$PATH" npx,npx)

IMAGE_NAME ?= open-webui
IMAGE_TAG  ?= latest

setup:
	uv sync --all-groups
	$(NPM) ci

build:
	docker build -t $(IMAGE_NAME):$(IMAGE_TAG) .

lint: format lint-frontend lint-backend

format: format-frontend format-backend

fix: format-backend format-frontend lint-backend lint-frontend
format-frontend:
	$(NPX) prettier --plugin-search-dir --write "**/*.{js,ts,svelte,css,md,html,json}"

format-backend:
	uv run ruff format . --exclude .venv --exclude venv

lint-frontend:
	$(NPX) eslint . --fix

lint-backend:
	uv run ruff check --fix .

