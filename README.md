# Kirana

Kirana is a local grocery finance QA prototype for answering questions over household receipts, receipt line items, Splitwise exports, and query-time item images.

The app is a FastAPI chat UI backed by a LangGraph agent. It combines structured finance lookup in Cloudflare D1 with semantic receipt and item retrieval in Cloudflare Vectorize, with model calls routed through Cloudflare AI Gateway.

## Get Running

Use Python 3.13+ and manage dependencies with `uv` from `app/`.

```sh
cd app
uv sync
uv run python main.py
```

Then open:

- Chat UI: `http://127.0.0.1:8000/`
- Swagger UI: `http://127.0.0.1:8000/docs`
- ReDoc: `http://127.0.0.1:8000/redoc`
- OpenAPI JSON: `http://127.0.0.1:8000/openapi.json`

For local runs that do not need Logfire:

```sh
cd app
KIRANA_DISABLE_LOGFIRE=1 uv run python main.py
```

The app expects Cloudflare, Tigris, model gateway, and optional Logfire environment variables in `app/.env` or the shell. See [docs/setup.md](docs/setup.md) for credential and infrastructure details.

## Common Commands

Provision or update infrastructure:

```sh
cd app
uv run python setup.py
```

Import source data and indexes:

```sh
cd app
uv run python ingest_kb.py
uv run python ingest_receipts.py
uv run python load_item_vectors.py
```

Run benchmarks with the local server already running:

```sh
cd app
uv run python bench.py --all
```

More setup, ingestion, API, and evaluation details live in [docs/](docs/README.md).

## Documentation Index

| Doc | Covers |
|---|---|
| [Setup](docs/setup.md) | Credentials, infrastructure resources, and `app/setup.py` behavior. |
| [Architecture](docs/architecture.md) | Chat graph, tools, stores, and retrieval modalities. |
| [Data Model](docs/data-model.md) | D1 tables, views, SQL indexes, Vectorize indexes, metadata fields, and local SQLite tables. |
| [Ingestion Pipeline](docs/ingestion.md) | Receipt ingestion, Splitwise import, item-vector indexing, storage responsibilities, and dry-run behavior. |
| [API Endpoints](docs/api.md) | FastAPI routes, request/response shapes, SSE events, and Swagger/OpenAPI locations. |
| [Evaluation](docs/evaluation.md) | Query families, ablation boundaries, benchmark commands, and metrics. |
| [Docs Index](docs/README.md) | Complete documentation index and common entry points. |

## Project Scope

Kirana is an early-stage research/prototype repo. The main design goal is to compare retrieval strategy against model tier while preserving clear ablation boundaries: SQL-only retrieval, hybrid SQL + Vectorize retrieval, weak vs. strong model tiers, and a plain-LLM baseline.

Raw receipts, exports, local databases, embeddings, generated artifacts, `.env`, and files under `knowledge-base/` should stay out of git.
