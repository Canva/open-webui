# Multi-stage build for the slim Open WebUI rebuild.
#
# Stage 1 (frontend): build the SvelteKit bundle with adapter-node.
# Stage 2 (pydeps):   resolve Python deps into a project-local venv via uv.
# Stage 3 (runtime):  copy the venv + the backend source + the FE build into a
#                     non-root, slim runtime image.
#
# Notes / deviations from the plan's quoted Dockerfile (see
# rebuild/docs/plans/m0-foundations.md § Dockerfile):
#   * Stage 1: build is invoked from /work (where vite.config.ts and svelte.config.js
#     live) rather than /work/frontend. SvelteKit's `kit.files` overrides in
#     svelte.config.js point at frontend/src/... so the build picks up the
#     correct source tree. Running vite from /work/frontend would fail with
#     "Could not resolve entry module 'index.html'" because vite.config.ts
#     is not in cwd and vite would fall back to default Rollup behavior.
#   * Stage 1: copy package-lock.json optionally (`*` glob) so the first-ever
#     image build before svelte-engineer commits the lockfile still works.
#   * Stage 2: kept `uv sync --frozen --no-dev --project backend` verbatim.
#   * Stage 2: install build-essential before `uv sync` because asyncmy 0.2.11
#     does not publish a `manylinux_2_17_aarch64` wheel for cp312 (only
#     macosx_arm64). On linux/arm64 build contexts (Apple Silicon Docker
#     Desktop) uv falls back to a source build that needs gcc + headers.
#     The compiler stays in the intermediate `pydeps` image; the runtime
#     image (stage 3) does not include it. If asyncmy publishes an aarch64
#     wheel in a future patch, this can be removed.
#   * Stage 3: kept the venv path /work/backend/.venv (uv sync --project
#     places the venv in the project root, which is /work/backend).
#   * Stage 3 / CMD: the plan's quoted CMD is
#       CMD ["uvicorn", "app.asgi:app", "--host", "0.0.0.0", "--port", "8080"]
#     We invoke uvicorn via `python -m uvicorn` instead. uv writes absolute
#     shebangs into the venv's bin/ scripts pointing at the build-time path
#     (/work/backend/.venv/bin/python). After we COPY the venv into
#     /app/.venv, those shebangs no longer resolve and the kernel reports
#     "missing dynamic library?" / "No such file or directory" for the
#     interpreter. `python -m uvicorn` runs the package's __main__ via the
#     venv's `python` symlink (which targets /usr/local/bin/python3.12) and
#     bypasses the broken script wrappers entirely. Surface this drift to
#     plan-keeper.
#   * Stage 3: we also create a phantom /work/backend/.venv -> /app/.venv
#     symlink so ad-hoc `docker exec` invocations of the other venv scripts
#     (alembic, mako-render, fastapi, openai, ...) keep working without
#     having to remember to prefix them with `python -m`. The symlink lives
#     entirely inside the runtime image; nothing on the host is touched.

# Stage 1 — frontend build
FROM --platform=$BUILDPLATFORM node:22-alpine3.20 AS frontend
WORKDIR /work
COPY package.json package-lock.json* ./
RUN npm ci --no-audit --no-fund || npm install --no-audit --no-fund
COPY tsconfig.json svelte.config.js vite.config.ts tailwind.config.ts postcss.config.cjs eslint.config.js .prettierrc.json ./
COPY frontend ./frontend
RUN npm run build

# Stage 2 — Python deps
FROM python:3.12.7-slim-bookworm AS pydeps
WORKDIR /work
RUN apt-get update && \
    apt-get install -y --no-install-recommends build-essential default-libmysqlclient-dev && \
    rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir uv==0.5.5
COPY pyproject.toml uv.lock* ./
COPY backend ./backend
RUN uv sync --frozen --no-dev --project backend

# Stage 3 — runtime
FROM python:3.12.7-slim-bookworm AS runtime
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PORT=8080
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*
RUN groupadd --system --gid 10001 app && \
    useradd  --system --uid 10001 --gid app --home-dir /app --shell /bin/false app
WORKDIR /app
COPY --from=pydeps   /work/backend/.venv  /app/.venv
COPY --from=pydeps   /work/backend        /app/backend
COPY --from=frontend /work/frontend/build /app/frontend
RUN mkdir -p /work/backend && ln -s /app/.venv /work/backend/.venv
ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONPATH="/app/backend"
USER app
EXPOSE 8080
HEALTHCHECK --interval=10s --timeout=3s --retries=10 \
  CMD curl -fsS http://localhost:${PORT}/healthz || exit 1
CMD ["python", "-m", "uvicorn", "app.asgi:app", "--host", "0.0.0.0", "--port", "8080"]
