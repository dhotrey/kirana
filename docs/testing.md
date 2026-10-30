# Testing

Kirana uses [pytest](https://docs.pytest.org/) from the `app/` directory. Tests are offline-first: they mock Cloudflare APIs, gateway calls, and heavy embedding loads unless a case explicitly needs local benchmark images.

## Running tests

```sh
cd app
uv sync
uv run pytest
```

Useful variants:

```sh
uv run pytest tests/test_chat_tools.py -q
uv run pytest -k validate_finance_sql
```

Pytest adds `app/` to `PYTHONPATH` via `[tool.pytest.ini_options]` in `app/pyproject.toml`.

## Layout

| Path | Focus |
|---|---|
| `tests/test_chat_service.py` | Conversation CRUD, SSE streaming shape, rate-limit retry behavior, Gemini in-agent tool loop vs LangGraph routing. |
| `tests/test_chat_tools.py` | `validate_finance_sql` allow/deny rules and D1 row parsing helpers. |
| `tests/test_vectorize_tools.py` | Receipt and item Vectorize tool contracts, embedding cache keys, filter metadata. |
| `tests/test_db_setup.py` | D1 DDL in `utils/db/db_setup.py` (tables, views, indexes). |
| `tests/test_ingest_kb.py` | Splitwise CSV import into `splits`. |
| `tests/test_ingestion_*.py` | Ingestion pipeline units: schemas, prompts, rate limits, disk/upload sources, canonical logs, Gemini client wiring, observability. |
| `tests/test_embeddings.py` | Local embedder configuration and dimension checks. |
| `tests/test_items_vectorize.py` | Item-name vector upsert logic for `load_item_vectors.py`. |
| `tests/test_setup_vectorize.py` | Vectorize index setup expectations from `setup.py`. |
| `tests/test_embedding_benchmark.py` | Optional embedding quality check against `utils/benchmarks/test-images/`; skipped when images are absent. |

Fixtures live under `tests/fixtures/` (for example structured receipt JSON used by ingestion tests).

## What is not covered in CI-style unit tests

- End-to-end chat against a live Cloudflare D1 database or Vectorize indexes.
- Full receipt ingestion with real Gemini/Mistral gateway calls (those paths are mocked or exercised via dry-run helpers documented in [ingestion](./ingestion.md)).
- Benchmark correctness (`app/bench.py`) — run manually with the server up; see [evaluation](./evaluation.md).

## Environment notes

- `app/main.py` sets `HF_HUB_OFFLINE=1` at import for the running app. Unit tests that load `SentenceTransformer` may still need cached model weights on the machine; see [troubleshooting](./troubleshooting.md#models-and-local-embeddings).
- Logfire is optional in tests. Some chat tests emit `LogfireNotConfiguredWarning` when spans are created without a configured token; this does not fail the suite.

## Expected baseline

After `uv sync`, a clean run should report **82 passed, 1 skipped** (the optional embedding benchmark skip when test images are missing). Re-run after changing chat tools, finance SQL validation, ingestion schemas, or Vectorize tool behavior.
