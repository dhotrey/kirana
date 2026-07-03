# Testing

Kirana uses [pytest](https://docs.pytest.org/) for unit and integration-style tests. Tests live under `app/tests/` and run without starting the FastAPI server or calling live Cloudflare APIs.

## Run Tests

From `app/`:

```sh
uv sync
uv run pytest
```

Useful variants:

```sh
# Quiet summary
uv run pytest -q

# One file or test
uv run pytest tests/test_chat_tools.py
uv run pytest tests/test_chat_tools.py::test_validate_finance_sql_rejects_receipt_splitwise_join

# Show skip/xfail reasons
uv run pytest -rs
```

Pytest is configured in `app/pyproject.toml` with `pythonpath = ["."]`, so imports resolve the same way as `uv run python main.py`.

## What Is Covered

| Area | Test files | What they verify |
|---|---|---|
| Chat service | `test_chat_service.py` | Rate-limit retry helper, Gemini tool-name extraction from `kirana_tool_names`, latest-turn tool counting |
| Finance SQL tool | `test_chat_tools.py` | `validate_finance_sql` allow/deny rules, D1 response parsing helpers |
| Vectorize tools | `test_vectorize_tools.py` | Receipt/item search input validation, metadata filter normalization, mock Vectorize client behavior |
| Embeddings | `test_embeddings.py`, `test_embedding_benchmark.py` | Local embedder shape and benchmark fixtures |
| Item vectors | `test_items_vectorize.py`, `test_setup_vectorize.py` | Item-name deduplication, Vectorize upsert IDs, setup index metadata |
| D1 / setup | `test_db_setup.py`, `test_ingestion_d1.py` | Schema DDL strings, receipt row mapping |
| Splitwise import | `test_ingest_kb.py` | CSV row parsing and cent conversion |
| Ingestion pipeline | `test_ingestion_*.py` | Gemini prompt building, rate limiting, canonical logs, schemas, observability, disk/upload sources, dry-run paths |

Most ingestion tests use mocks or fixtures instead of real gateway calls. They are meant to lock in validation, retry, and data-shaping behavior that evaluation depends on.

## What Is Not Covered

These paths still need manual or benchmark verification:

- End-to-end chat over `/api/chat/stream` and `/api/chat/image/stream` against a running server with ingested data
- Live Cloudflare D1, Vectorize, Tigris, and AI Gateway calls
- QF1–QF4 benchmark correctness (see [evaluation](./evaluation.md))

Run `uv run python bench.py` only with `main.py` already serving on `http://127.0.0.1:8000`.

## Environment Notes

- Tests do not require `app/.env` for most modules. Finance and Vectorize tool tests use in-memory or stub clients.
- Embedding-related tests may download or expect cached Hugging Face weights on first run. `main.py` sets `HF_HUB_OFFLINE=1` at import for the app, but pytest imports modules directly; see [troubleshooting](./troubleshooting.md#models-and-local-embeddings) if model load fails locally.
- One test is intentionally skipped when optional GPU/runtime dependencies are unavailable; use `pytest -rs` to see the reason.

## Adding Tests

Follow existing conventions:

- Place new tests beside related modules under `app/tests/`.
- Prefer focused assertions on validation, SQL safety, and serialization rather than full LLM output checks.
- For financial behavior, align expected tolerances with [evaluation](./evaluation.md) unless the test is explicitly about exact benchmark cases.
- Run `uv run pytest` from `app/` before opening a PR that changes chat, tools, ingestion, or schema code.
