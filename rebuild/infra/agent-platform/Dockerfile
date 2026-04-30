# Multi-stage build for the agent-platform service.
#
# Stage 1 (pydeps):  resolve Python deps into a project-local venv via uv.
# Stage 2 (runtime): copy the venv + the app source into a non-root, slim
#                    runtime image.
#
# Divergences from rebuild/Dockerfile (the rebuild backend's image):
#   * No frontend stage. The platform is a pure backend service.
#   * No default-libmysqlclient-dev / build-essential. The platform has no
#     DB driver — pydantic-ai + httpx + uvicorn all ship pure-python or
#     prebuilt wheels for python:3.12 on linux/amd64 + linux/arm64.
#   * CMD uses `python -m uvicorn` (not the venv's `uvicorn` script
#     wrapper) for the same shebang-portability reason called out in
#     rebuild/Dockerfile lines 28-38: uv writes absolute shebangs into
#     the venv's bin/ scripts pointing at the build-time venv path; after
#     COPY into a different prefix the script wrappers no longer resolve
#     their interpreter. `python -m uvicorn` runs the package's __main__
#     via the venv's `python` symlink and bypasses the broken shebang.

# Stage 1 — Python deps
FROM python:3.12.7-slim-bookworm AS pydeps
WORKDIR /work
RUN pip install --no-cache-dir uv==0.5.5
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# Stage 2 — runtime
FROM python:3.12.7-slim-bookworm AS runtime
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PORT=8081
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*
RUN groupadd --system --gid 10001 app && \
    useradd  --system --uid 10001 --gid app --home-dir /app --shell /bin/false app
WORKDIR /app
COPY --from=pydeps /work/.venv /app/.venv
COPY app /app/app
ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONPATH="/app"
USER app
EXPOSE 8081
HEALTHCHECK --interval=10s --timeout=3s --retries=10 \
  CMD curl -fsS http://localhost:${PORT}/healthz || exit 1
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8081"]
