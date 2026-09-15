# Backend

FastAPI backend for RegRag: the ingestion pipeline, the retrieval layer, and the
chat API that answers from them.

## Stack

| Component              | Technology                                                    |
| ---------------------- | ------------------------------------------------------------- |
| Web Framework          | [FastAPI](https://github.com/fastapi/fastapi)                 |
| Database               | [PostgreSQL](https://www.postgresql.org/)                     |
| Vector Search          | [pgvector](https://github.com/pgvector/pgvector)              |
| Object Storage         | [Cloudflare R2](https://developers.cloudflare.com/r2/)        |
| ORM                    | [SQLAlchemy](https://github.com/sqlalchemy/sqlalchemy)        |
| Database Migrations    | [Alembic](https://github.com/sqlalchemy/alembic)              |
| Data Validation        | [Pydantic](https://github.com/pydantic/pydantic)              |
| LLM Gateway            | [LiteLLM](https://github.com/BerriAI/litellm)                 |
| Embeddings             | [Voyage](https://docs.voyageai.com/)                          |
| HTML Parsing           | [selectolax](https://github.com/rushter/selectolax)           |
| Containerisation       | [Docker](https://www.docker.com)                              |
| Python Package Manager | [uv](https://github.com/astral-sh/uv)                         |
| Linter                 | [Ruff](https://github.com/astral-sh/ruff)                     |
| Type Checker           | [ty](https://github.com/astral-sh/ty)                         |

## Layout

| Directory                                            | Contents                                                      |
| ---------------------------------------------------- | ------------------------------------------------------------- |
| `app/core/`                                          | Shared contracts: config, db session, http, llm, storage      |
| [`app/ingestion/`](app/ingestion/README.md)          | The corpus pipeline: discover → fetch → parse → chunk → embed |
| [`app/retrieval/`](app/retrieval/README.md)          | The read side: hybrid search and exact article lookup         |
| [`app/chat/`](app/chat/README.md)                    | The answering graph, its SSE endpoint, and the request ledger |
| [`app/evals/`](app/evals/README.md)                  | The golden dataset and the runner that scores the graph on it |
| `migrations/`                                        | Alembic revisions                                             |
| `tests/`                                             | Mirrors `app/`, with shared fixtures in `tests/conftest.py`   |

`app/core/` holds only what two or more capabilities use. Anything used by one
capability lives in that capability's package.

Each capability package follows the same file convention:

| File          | Purpose                                  |
| ------------- | ---------------------------------------- |
| `schemas.py`  | SQLAlchemy ORM models                    |
| `models.py`   | Pydantic request/response/value models   |
| `enums.py`    | Enumerations the capability owns         |
| `service.py`  | Database reads and writes                |
| `pipeline.py` | Orchestration across stages              |
| `router.py`   | FastAPI endpoints (where applicable)     |
| `cli.py`      | argparse entry point, listed in `[project.scripts]` |

New ORM schemas must be imported in `app/core/db/registry.py` so their mappers
register; a guard test fails if one is missing.

The four capability directories link to their own READMEs, which cover how each
works and why it is built that way.

## Setup

Prerequisites: [uv](https://docs.astral.sh/uv/getting-started/installation/),
[pre-commit](https://pre-commit.com/#install), Docker running.

```bash
uv sync
pre-commit install          # from the repo root
cp .env.example .env.dev    # then set VOYAGE_API_KEY and ANTHROPIC_API_KEY
```

Start the database, migrate and run the API:

```bash
docker compose up -d db
uv run alembic upgrade head
uv run fastapi dev
```

The API is then on `http://localhost:8000`, with `/health` reporting database
connectivity and `/docs` serving the OpenAPI schema.

The same stack runs entirely in compose, which needs nothing on the host but
Docker and `.env.dev`:

```bash
docker compose up --watch
```

This builds the API image, migrates the database, and serves the API on the
same port, syncing source edits into the container as you save. Running the
API on the host with `uv run fastapi dev` stays the faster inner loop. The
frontend runs on the host either way (`pnpm dev` in `frontend/`).

## Commands

```bash
uv run ingest                  # build the corpus; `ingest fueleu` for one topic
uv run retrieve "query"        # search it from the terminal
uv run evals run               # score the chat graph against the golden dataset
uv run evals tune              # sweep retrieval settings against the same cases
```

Each is an argparse entry point that self-documents: `--help` prints what it
does and every flag it takes.

`ingest` needs `VOYAGE_API_KEY`, `evals run` also needs `ANTHROPIC_API_KEY`, and
re-running `ingest` is cheap — unchanged documents are neither downloaded nor
re-embedded. In production `ingest` runs nightly from `.github/workflows/ingest.yml`.
