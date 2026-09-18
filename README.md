# Kirana

Kirana is a local grocery finance QA prototype for answering questions over household receipts, receipt line items, Splitwise exports, and query-time item images.

The app is a FastAPI chat UI backed by a LangGraph agent. It combines structured finance lookup in Cloudflare D1 with semantic receipt and item retrieval in Cloudflare Vectorize, with model calls routed through Cloudflare AI Gateway.

## Get Running

Use Python 3.13+ and manage dependencies with `uv` from `app/`. A functional local app requires provisioned Cloudflare/Tigris resources, Cloudflare AI Gateway provider keys, Logfire configured or explicitly disabled, and ingested data. Starting the server before setup and ingestion will bring up the UI, but grocery finance answers will not work.

```sh
cd app
uv sync
```

1. Create `app/.env` with the required Cloudflare and Tigris credentials. See [setup credentials](docs/setup.md#required-env).

2. Provision or update the remote resources:

```sh
uv run python setup.py
```

3. Finish the manual Cloudflare AI Gateway setup. `setup.py` creates the gateway resource, but it does not enable Authenticated Gateway or install upstream provider API keys. Add the gateway auth token to `app/.env` and configure provider keys before ingestion. See [Cloudflare AI Gateway setup](docs/setup.md#finish-cloudflare-ai-gateway-setup).

4. Configure Logfire before ingestion, or explicitly disable it. See [Logfire setup](docs/setup.md#logfire-setup).

5. Ingest the Splitwise export, receipt images, and item-vector index:

```sh
uv run python ingest_kb.py
uv run python ingest_receipts.py
uv run python load_item_vectors.py
```

6. Start the app:

```sh
uv run python main.py
```

For local runs that do not need Logfire:

```sh
KIRANA_DISABLE_LOGFIRE=1 uv run python main.py
```

Open:

- Chat UI: `http://127.0.0.1:8000/`
- Swagger UI: `http://127.0.0.1:8000/docs`
- ReDoc: `http://127.0.0.1:8000/redoc`
- OpenAPI JSON: `http://127.0.0.1:8000/openapi.json`

See [docs/setup.md](docs/setup.md) for credential and infrastructure details, and [docs/ingestion.md](docs/ingestion.md) for dry-run and single-image ingestion options.

## Common Commands

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
| [Testing](docs/testing.md) | Pytest commands, suite layout, and local test environment notes. |
| [Troubleshooting](docs/troubleshooting.md) | Chat tool errors, embedding cache, gateway setup, and ingestion pitfalls. |
| [Docs Index](docs/README.md) | Complete documentation index and common entry points. |

## Project Scope

Kirana is an early-stage research/prototype repo. The main design goal is to compare retrieval strategy against model tier while preserving clear ablation boundaries: SQL-only retrieval, hybrid SQL + Vectorize retrieval, weak vs. strong model tiers, and a plain-LLM baseline.

Raw receipts, exports, local databases, embeddings, generated artifacts, `.env`, and files under `knowledge-base/` should stay out of git.
