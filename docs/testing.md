# Testing

Kirana uses `pytest` for unit and integration-style tests that run without Cloudflare credentials, a running server, or ingested data. Tests live under `app/tests/` and are configured in `app/pyproject.toml` with `pythonpath = ["."]`.

## Running Tests

From `app/`:

```sh
uv sync
uv run pytest
```

Useful variants:

```sh
uv run pytest -q                          # quiet summary
uv run pytest tests/test_chat_tools.py    # one module
uv run pytest -k finance_sql              # name filter
```

As of August 2026 the suite reports **82 passed, 1 skipped**.

## What Is Covered

| Area | Test modules | What they verify |
|---|---|---|
| Chat service | `test_chat_service.py` | Tool-name extraction for LangGraph and Gemini turns, Cloudflare 429 detection, rate-limit retry backoff |
| Finance tools | `test_chat_tools.py` | `validate_finance_sql` allow/deny rules, D1 response unwrapping |
| Vectorize tools | `test_vectorize_tools.py` | Metadata filter validation, match normalization, config defaults for item/receipt search |
| Item vectors | `test_items_vectorize.py` | Item-name normalization, deterministic vector IDs, D1 fetch/dedupe, Vectorize upsert rollback |
| Embeddings | `test_embeddings.py` | Image resize/downscale behavior for query-time and ingestion embeddings |
| DB setup | `test_db_setup.py`, `test_setup_vectorize.py` | Splitwise share views, Vectorize index creation metadata |
| Ingestion core | `test_ingestion_*.py` | Receipt schemas, Gemini prompt assembly, rate limiting, D1 SQL builders, canonical logs, disk/upload sources |
| Splitwise import | `test_ingest_kb.py` | CSV money conversion, batch insert sizing for D1 variable limits |
| Embedding benchmark | `test_embedding_benchmark.py` | Optional local image benchmark (skipped unless `KIRANA_RUN_EMBEDDING_BENCHMARK=1`) |

## What Is Not Covered

These paths require live infrastructure or manual setup and are exercised outside pytest:

- End-to-end chat over `/api/chat/stream` and `/api/chat/image/stream` — use `uv run python main.py` plus `uv run python bench.py` ([evaluation](./evaluation.md)).
- Receipt ingestion against Gemini, Mistral, D1, Vectorize, and Tigris — run `ingest_receipts.py` after [setup](./setup.md).
- Cloudflare AI Gateway authentication and provider keys — validated during ingestion or chat, not in CI unit tests.

## Finance SQL Validation

`query_finance_db` rejects writes, comments, multi-statement SQL, unknown tables, and joins that mix receipt tables with Splitwise accounting tables in one query. See `app/tools/finance.py` and `test_chat_tools.py` for the authoritative rules. At query time the agent must run receipt totals and Splitwise personal-share lookups as separate SQL calls, then reconcile in natural language.

## Local Conventions

- Prefer focused tests next to the module they protect (`chat/`, `tools/`, `ingestion/`).
- Use fixtures under `app/tests/fixtures/` for stable receipt JSON samples.
- When adding tool routing, SQL validation, or ingestion schema rules, add or extend tests in the same change.
