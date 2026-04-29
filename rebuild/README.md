# Open WebUI rebuild

This is the **slim rebuild** of Open WebUI for internal use at Canva. It lives next to the legacy fork (everything else in this repo) so PRs can keep merging to `main` while the rebuild is built milestone by milestone. On cutover (end of M5) the contents of this directory are promoted to the repo root and the legacy tree is deleted in a single sweep PR. Until then, both trees are independent: separate Python deps, separate npm deps, separate Docker images, separate Buildkite pipelines (path-filtered so each only runs on changes to its own tree).

## Stack

Python 3.12 + FastAPI + SQLAlchemy 2 (async, asyncmy) + Alembic on the backend, SvelteKit 2 + Svelte 5 + Tailwind 4 on the frontend, MySQL 8.0 + Redis 7 for infra. Identifiers are UUIDv7 strings (`app.core.ids.new_id()`); timestamps are epoch-ms BIGINTs (`app.core.time.now_ms()`). Auth is the trusted-header path only (`X-Forwarded-Email` from the OAuth proxy) — no JWT, no sessions, no `auth` table. The dev compose stack uses a static MySQL container password; **production connects to AWS Aurora MySQL behind RDS IAM database authentication** (`DATABASE_IAM_AUTH=True`, token minted per physical SQLAlchemy connection via `app.core.iam_auth`; see [plans/m0-foundations.md § IAM database authentication](plans/m0-foundations.md#iam-database-authentication)). The full target architecture and locked decisions are in [`../rebuild.md`](../rebuild.md).

## Quickstart

Install Python via [`uv`](https://github.com/astral-sh/uv) and node 22+ first, then from this directory:

```sh
make setup       # uv sync + npm ci
make dev         # docker compose up -d --wait (mysql + redis + app)
make migrate     # alembic upgrade head against dev MySQL
curl -H 'X-Forwarded-Email: alice@canva.com' localhost:8080/api/me
```

`make lint`, `make typecheck`, `make test-unit`, `make test-component`, and `make test-e2e-smoke` are the standard developer loops; the same commands run in the [Buildkite pipeline](.buildkite/rebuild.yml) (only the rebuild pipeline runs on `rebuild/**` changes; only the legacy pipeline runs on legacy changes).

## Layout

```
backend/         FastAPI app (app/), Alembic env + migrations
frontend/        SvelteKit 2 app (built into the same Docker image)
infra/           docker-compose.yml + mysql/, redis/ configs
plans/           per-milestone implementation plans (M0..M5)
.buildkite/      rebuild CI pipeline
Dockerfile       multi-stage build (frontend → pydeps → runtime)
pyproject.toml   single Python project; backend/pyproject.toml is a symlink here
package.json     single JS project (added by svelte-engineer); frontend/package.json symlinks here
```

## Plans

The rebuild ships in five milestones; each has a binding plan under [`plans/`](plans/):

- [M0 — Foundations](plans/m0-foundations.md): the contents of this directory.
- [M1 — Conversations](plans/m1-conversations.md), [M2 — Sharing](plans/m2-sharing.md), [M3 — Channels](plans/m3-channels.md), [M4 — Automations](plans/m4-automations.md), [M5 — Hardening](plans/m5-hardening.md).

The top-level [`../rebuild.md`](../rebuild.md) is the parent plan; the per-milestone files are the binding contracts for what each milestone delivers.
