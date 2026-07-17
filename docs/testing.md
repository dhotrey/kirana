# Testing

Kirana uses [pytest](https://docs.pytest.org/) for unit and integration-style tests. Tests live under `app/tests/` and run against local modules without requiring a live Cloudflare stack, running chat server, or ingested knowledge base.

## Running Tests

From `app/`:

```sh
uv sync
uv run pytest
```

Useful variants:

```sh
# Quiet summary
uv run pytest -q

# One file
uv run pytest tests/test_chat_tools.py

# One test by name
uv run pytest tests/test_chat_tools.py::test_validate_finance_sql_rejects_receipt_splitwise_join -q
```

Pytest is configured in `app/pyproject.toml` with `pythonpath = ["."]`, so imports resolve the same way as `uv run python main.py`.

## What Is Covered

| Area | Test modules | What they verify |
|---|---|---|
| Chat service | `test_chat_service.py` | Rate-limit retry backoff, Gemini in-agent tool loop, conversation helpers |
| Chat tools | `test_chat_tools.py` | Finance SQL validation, vector tool wiring, receipt/Splitwise join guard |
| Vectorize tools | `test_vectorize_tools.py` | Metadata filter normalization, match parsing, config defaults |
| Item vectors | `test_items_vectorize.py` | Item-name normalization, vector IDs, partial-run rollback on failure |
| Embeddings | `test_embeddings.py`, `test_embedding_benchmark.py` | Local embedder behavior and benchmark helpers |
| Ingestion schemas | `test_ingestion_schemas.py` | Pydantic receipt validation, sum tolerance, date rules |
| Ingestion pipeline | `test_ingestion_d1.py`, `test_ingestion_gemini.py`, `test_ingestion_canonical_log.py`, `test_ingestion_observability.py`, `test_ingestion_prompts.py`, `test_ingestion_rate_limit.py`, `test_ingestion_sources.py` | D1 writes, Gemini retry paths, logging, prompts, rate limiting, image sources |
| Splitwise import | `test_ingest_kb.py` | CSV parsing and D1 batch insert |
| Infrastructure setup | `test_db_setup.py`, `test_setup_vectorize.py` | D1 schema/index creation and Vectorize index provisioning |

Tests use fixtures such as `app/tests/fixtures/receipt.json` where structured receipt JSON is needed.

## What Tests Do Not Cover

- End-to-end chat against a running `main.py` server with live D1 and Vectorize (see [evaluation](./evaluation.md) and `app/bench.py` instead).
- Receipt image ingestion against real Gemini or Mistral models (ingestion tests mock or stub external calls).
- Hugging Face model download; embedding tests may skip or mock when weights are unavailable.

## Local Conventions

- Prefer focused tests next to the module they exercise (`app/chat/`, `app/tools/`, `app/ingestion/`).
- Finance SQL validation rules in `app/tools/finance.py` should have matching tests in `test_chat_tools.py` when behavior changes.
- When adding API endpoints or tool contracts, add or extend tests before updating [api.md](./api.md).

## Before Finishing Code Changes

Run the narrowest relevant check:

```sh
cd app
uv run pytest -q
```

For chat-only changes, `uv run pytest tests/test_chat_service.py tests/test_chat_tools.py -q` is usually enough. For ingestion changes, include the matching `test_ingestion_*.py` modules.
