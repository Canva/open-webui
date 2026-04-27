# Local Development With Docker Compose Services

This repository can run Open WebUI locally while continuing to use `agents`
and MySQL from a separate `docker-compose` stack.

## Requirements

Your compose stack must publish the backing services to the host:

- `agents` on a host port that is **not** `5080`
- MySQL on a host port, typically `3306`

`5080` must stay free for the local Open WebUI backend because the Svelte dev
frontend is hard-coded to talk to `http://localhost:5080` in development mode.

## Environment

1. Copy `local-compose.env.example` to `.env`
2. Update the OpenAI-compatible endpoint URLs to match the host port exposed for `agents`
3. Update the MySQL host port if your compose stack publishes a non-default port

Example:

```env
OPENAI_API_BASE_URL=http://localhost:8081/v1
OPENAI_API_BASE_URLS=http://localhost:8081/v1
OPENAI_API_KEYS=dummy
OFFLINE_MODE=true
RAG_EMBEDDING_ENGINE=openai
RAG_OPENAI_API_BASE_URL=http://localhost:8081/v1
RAG_OPENAI_API_KEY=dummy
ENABLE_OLLAMA_API=false
ENABLE_EVALUATION_ARENA_MODELS=false
WEBUI_AUTH=false
WEBUI_NAME=Canva Agents Platform
DEFAULT_USER_ROLE=admin
ENABLE_NOTES=false
DATABASE_TYPE=mysql
DATABASE_HOST=localhost
DATABASE_PORT=3306
DATABASE_NAME=openwebui
DATABASE_USER=openwebui
DATABASE_PASSWORD=openwebui
CORS_ALLOW_ORIGIN=http://localhost:5173;http://localhost:5080
```

If MySQL connection attempts on `localhost` fail because the client resolves to
IPv6 first, use `127.0.0.1` instead.

`OFFLINE_MODE=true` is important for this setup: it stops the backend from
trying to initialize the default local `sentence-transformers` embedding model,
which otherwise triggers Hugging Face downloads during startup.

## Running Open WebUI

Install dependencies once:

```bash
make setup
```

Run the backend in one terminal:

```bash
make dev-backend
```

Run the frontend in another terminal:

```bash
make dev-frontend
```

Then open `http://localhost:5173`.

The backend will listen on `http://localhost:5080`, and the frontend will send
API requests there while the backend connects onward to your compose-backed
`agents` and MySQL services.
