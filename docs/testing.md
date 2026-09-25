# Testing

Kirana uses pytest from the `app/` uv environment. Tests focus on deterministic pieces—finance SQL validation, ingestion helpers, embedding prep, Vectorize ID rules, and chat service utilities—rather than live Cloudflare or gateway calls.

## Running tests

```sh
cd app
uv sync
uv run pytest
```

Useful variants:

```sh
uv run pytest app/tests/test_chat_tools.py -q
uv run pytest -k finance -q
```

As of the current suite, expect **82 passed** and **1 skipped** on a clean sync (the skipped case is the optional local embedding benchmark in `test_embedding_benchmark.py`).

## Layout

All tests live under `app/tests/`. Fixtures such as `app/tests/fixtures/receipt.json` support ingestion schema checks.

| Module | What it covers |
|---|---|
| `test_chat_service.py` | Tool-name extraction (including Gemini `kirina_tool_names`), rate-limit detection, and retry backoff on model calls. |
| `test_chat_tools.py` | `query_finance_db` SQL validation, allowed tables, and the receipts vs. Splitwise join restriction. |
| `test_vectorize_tools.py` | Receipt query embedding cache keys and Vectorize search tool wiring. |
| `test_db_setup.py` | D1 DDL in `utils/db/db_setup.py` (tables, views, indexes). |
| `test_setup_vectorize.py` | Vectorize index and metadata index creation from setup. |
| `test_ingest_kb.py` | Splitwise CSV cent conversion and D1 batch insert preparation. |
| `test_ingestion_d1.py` | Receipt row SQL builders and D1 response parsing. |
| `test_ingestion_schemas.py` | Pydantic receipt and pipeline schemas. |
| `test_ingestion_gemini.py` | Gemini extraction prompt shape (image payload, retries). |
| `test_ingestion_prompts.py` | Prompt file loading and cache behavior. |
| `test_ingestion_canonical_log.py` | Canonical ingestion log JSON shape. |
| `test_ingestion_observability.py` | Logfire disable flag behavior. |
| `test_ingestion_rate_limit.py` | Gemini min-interval limiter and retry strategies. |
| `test_ingestion_sources.py` | Disk and upload image sources for ingestion. |
| `test_embeddings.py` | Image resize rules before local embedding. |
| `test_items_vectorize.py` | Item-name normalization and Vectorize ID/metadata for `load_item_vectors.py`. |
| `test_embedding_benchmark.py` | Optional end-to-end local image embedding benchmark (skipped unless run explicitly). |

## What tests do not cover

- A running FastAPI server or full LangGraph chat turns against Cloudflare AI Gateway.
- Live D1, Vectorize, or Tigris mutations (those paths use mocks or pure functions).

For manual smoke checks after infrastructure setup, use [setup](./setup.md) and `uv run python main.py`. For agent quality comparisons, use [evaluation](./evaluation.md) and `bench.py` with the app already listening on port 8000.
