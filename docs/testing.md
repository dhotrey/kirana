# Testing

Kirana uses `pytest` for unit and integration tests. Tests live under `app/tests/` and run against the local Python environment managed by `uv`.

## Quick Start

From `app/`:

```sh
uv sync
uv run pytest
```

Run a single file or test:

```sh
uv run pytest tests/test_chat_service.py
uv run pytest tests/test_chat_tools.py::test_validate_finance_sql_rejects_receipt_and_splitwise_join
```

Verbose output with tracebacks:

```sh
uv run pytest -v
```

## Current Coverage

As of September 2026, the suite reports **82 passed, 1 skipped**. The skipped case is `test_embedding_benchmark.py`, which requires benchmark images under `app/utils/benchmarks/test-images/` and is skipped when that directory is empty.

Tests do not require Cloudflare credentials, a running server, or ingested knowledge-base data unless noted in the test module. Most tests use mocks, fixtures, or in-memory databases.

## Test Areas

| Area | Files | What they verify |
|---|---|---|
| Chat service | `test_chat_service.py` | LangGraph wiring, SSE streaming helpers, rate-limit retry backoff, Gemini in-agent tool loop, image-upload context |
| Chat tools | `test_chat_tools.py` | Finance SQL validation, tool JSON shapes, receipt/Splitwise table isolation |
| Vectorize tools | `test_vectorize_tools.py` | Embedding cache keys, metadata filter validation, Vectorize match parsing |
| Database setup | `test_db_setup.py` | D1 schema DDL, expense views, index creation |
| Ingestion core | `test_ingestion_*.py` | Receipt schemas, prompts, Gemini extraction retries, D1 writes, canonical logs, rate limiting, observability |
| Ingestion CLIs | `test_ingest_kb.py`, `test_items_vectorize.py`, `test_ingestion_sources.py` | Splitwise import, item-vector loading, disk/upload sources |
| Embeddings | `test_embeddings.py`, `test_embedding_benchmark.py` | Local Qwen embedder behavior and optional image benchmark |
| Infrastructure setup | `test_setup_vectorize.py` | Vectorize index provisioning helpers |

## Fixtures

- `app/tests/fixtures/receipt.json`: sample structured receipt used by ingestion schema tests.
- `app/utils/benchmarks/test-images/`: optional images for embedding benchmark tests (not committed when empty).

## Environment Notes

- `main.py` sets `HF_HUB_OFFLINE=1` at import time. Embedding-related tests that load `Qwen/Qwen3-VL-Embedding-2B` expect model weights to already be cached locally, or they mock the embedder.
- Logfire is not configured during most tests. A `LogfireNotConfiguredWarning` from rate-limit retry spans is expected and does not fail the suite.
- Chat and benchmark integration tests that hit a live server are not part of this pytest suite; use `uv run python main.py` plus `uv run python bench.py` for end-to-end checks ([evaluation](./evaluation.md)).

## Before Committing

Run the narrowest relevant check for the area you changed:

```sh
cd app
uv run pytest tests/test_<area>.py
```

For broad changes touching chat, tools, or ingestion, run the full suite:

```sh
cd app
uv run pytest
```
