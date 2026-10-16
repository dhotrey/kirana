# Testing

Kirana uses `pytest` for unit and integration-style tests. Tests live under `app/tests/` and run against the local Python environment managed by `uv`. They do not require Cloudflare credentials, a running chat server, or ingested knowledge-base data unless a test file explicitly loads models or images.

## Run tests

From `app/`:

```sh
uv sync
uv run pytest
```

Useful variants:

```sh
uv run pytest -q                    # quiet summary
uv run pytest tests/test_chat_tools.py -k splitwise
uv run pytest --co -q               # list collected tests without running
```

As of October 2026 the suite reports **82 passed, 1 skipped** on a clean `uv sync` environment.

## What is covered

| Area | Test modules | Notes |
|---|---|---|
| Chat agent | `test_chat_service.py` | Tool-name extraction for LangGraph and Gemini paths, 429 detection, rate-limit retry wrapper. |
| Finance SQL tool | `test_chat_tools.py` | `validate_finance_sql` allow/deny rules, including the receipts vs. Splitwise separation constraint. |
| D1 helpers | `test_db_setup.py` | Splitwise expense view columns, Cloudflare D1 response envelope parsing. |
| Vectorize tools | `test_vectorize_tools.py` | Filter validation, match normalization, config defaults for search `top_k` and image thresholds. |
| Embeddings (chat/ingest) | `test_embeddings.py` | Image resize rules for local `Qwen` embedding (max dimension, no upscale). |
| Splitwise import | `test_ingest_kb.py` | CSV money conversion, batched D1 insert statement building. |
| Receipt ingestion | `test_ingestion_*.py`, `test_ingestion_d1.py` | Pydantic receipt validation, Gemini prompt assembly, D1 insert SQL, canonical logs, rate limiter, disk/upload sources. |
| Item vectors | `test_items_vectorize.py`, `test_setup_vectorize.py` | Distinct item-name fetch, per-vector upsert rollback, Vectorize index setup metadata. |
| Embedding benchmark | `test_embedding_benchmark.py` | Optional local benchmark over `app/utils/benchmarks/test-images/`; **skipped** when that directory has no images. |

Fixtures such as `app/tests/fixtures/receipt.json` support schema round-trip tests without calling remote APIs.

## What is not covered

- End-to-end chat against a live `uv run python main.py` server (see `app/bench.py` and [evaluation](./evaluation.md)).
- Full receipt ingestion with Gemini, Mistral, D1, Vectorize, and Tigris in one pytest case.
- UI behavior in `app/index.html`.

When changing tool validation, ingestion SQL, or chat routing (especially the Gemini in-agent tool loop in `app/chat/service.py`), extend the closest module in the table above rather than adding network-dependent tests.

## CI and local parity

The repository does not ship a dedicated GitHub Actions test workflow yet. Treat `cd app && uv run pytest` as the pre-merge check for Python changes, alongside `uv run python main.py` for app smoke tests per [AGENTS.md](../AGENTS.md).
