# Testing

Kirana uses `pytest` from the `app/` directory. Tests are offline and do not require Cloudflare credentials, a running server, or ingested data unless a case explicitly mocks remote calls.

## Run Tests

```sh
cd app
uv sync
uv run pytest
```

Useful variants:

```sh
uv run pytest -q                    # quiet summary
uv run pytest tests/test_chat_tools.py -v   # one module
uv run pytest -k "finance_sql"      # name filter
```

The pytest `pythonpath` is set to `app/` in `app/pyproject.toml`, so imports match runtime modules (`chat`, `ingestion`, `tools`, `utils`).

## What Is Covered

| Area | Test modules | Focus |
|---|---|---|
| Chat service | `test_chat_service.py` | Rate-limit retries, Gemini vs LangGraph routing hooks, conversation lifecycle |
| Finance tools | `test_chat_tools.py` | `validate_finance_sql` allow/deny rules, D1 row parsing helpers |
| Vectorize tools | `test_vectorize_tools.py`, `test_items_vectorize.py`, `test_setup_vectorize.py` | Receipt and item search tool wiring, index metadata |
| Embeddings | `test_embeddings.py`, `test_embedding_benchmark.py` | Local Qwen embedder shape and resize behavior |
| Ingestion | `test_ingestion_*.py`, `test_ingest_kb.py` | Schemas, Gemini/Mistral prompts, D1 writes, rate limits, observability |
| Database setup | `test_db_setup.py` | D1 schema creation SQL for tables, views, and indexes |

Finance SQL validation tests assert that `query_finance_db` rejects joins between `receipts` and Splitwise views in a single statement. Run two queries and reconcile in the agent instead (`app/tools/finance.py`).

## Logfire During Tests

Some chat tests exercise code paths that emit Logfire spans. If Logfire is not configured, pytest may print a `LogfireNotConfiguredWarning`. This does not fail the suite. For local runs, set `KIRANA_DISABLE_LOGFIRE=1` or configure `LOGFIRE_TOKEN` per [setup](./setup.md#logfire-setup).

## Relationship to Benchmarks

`app/bench.py` and `app/utils/benchmarks/` exercise the live HTTP API against a running server and ingested knowledge base. They are evaluation harnesses, not unit tests. See [evaluation](./evaluation.md).
