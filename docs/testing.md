# Testing

Kirana uses [pytest](https://docs.pytest.org/) for unit and integration-style tests. Tests live under `app/tests/` and run from `app/` with `uv`.

## Run the suite

```sh
cd app
uv sync
uv run pytest
```

Useful variants:

```sh
# Quiet summary
uv run pytest -q

# One file or test
uv run pytest tests/test_chat_tools.py
uv run pytest tests/test_chat_service.py::test_invoke_model_retries_rate_limits

# Stop on first failure
uv run pytest -x
```

As of September 2026 the suite reports **82 passed, 1 skipped**.

## Layout

| Area | Test files | What they cover |
|---|---|---|
| Chat service | `test_chat_service.py` | Rate-limit retries, tool-name extraction (including Gemini `kirana_tool_names` metadata). |
| Chat tools | `test_chat_tools.py` | `query_finance_db` SQL validation, D1 response parsing, receipt/Splitwise table separation. |
| Vectorize tools | `test_vectorize_tools.py` | Receipt and item vector search tool contracts. |
| Ingestion pipeline | `test_ingestion_*.py`, `test_ingest_kb.py` | Gemini extraction prompts, schemas, D1 writes, rate limiting, observability, canonical logs, source loading. |
| Embeddings | `test_embeddings.py`, `test_embedding_benchmark.py`, `test_items_vectorize.py` | Local Qwen embedding behavior and item-vector ingestion. |
| Infrastructure | `test_db_setup.py`, `test_setup_vectorize.py` | D1 schema setup and Vectorize index configuration. |

Tests are designed to run without live Cloudflare credentials. Chat, finance, and vectorize tests use fakes or in-memory fixtures; ingestion tests mock external APIs where needed.

## Environment notes

- `pythonpath` is set to `app/` in `pyproject.toml`, so imports match runtime (`from chat.service import ...`).
- Logfire may emit `LogfireNotConfiguredWarning` during chat tests when `LOGFIRE_TOKEN` is unset. This does not fail the suite. For quieter local runs, set `KIRANA_DISABLE_LOGFIRE=1` or `LOGFIRE_IGNORE_NO_CONFIG=1`.
- Embedding tests may download or cache Hugging Face model weights on first run. `main.py` sets `HF_HUB_OFFLINE=1` at import for the app server; tests that load `SentenceTransformer` directly may still need network or a populated cache.

## What to test when changing code

| Change | Suggested check |
|---|---|
| `query_finance_db` validation or allowed tables | `tests/test_chat_tools.py` |
| Vectorize search tools or embedding cache | `tests/test_vectorize_tools.py`, `tests/test_items_vectorize.py` |
| Chat streaming, rate limits, Gemini routing | `tests/test_chat_service.py` |
| Receipt ingestion stages | Matching `tests/test_ingestion_*.py` module |
| D1 schema or views | `tests/test_db_setup.py` |
| Benchmark harness client | `app/utils/benchmarks/` (see [benchmark README](../app/utils/benchmarks/README.md)) |

End-to-end grocery finance answers still require a running server, ingested data, and `uv run python bench.py` ([evaluation](./evaluation.md)).

## Adding tests

- Place new modules beside related code: `app/tests/test_<module>.py`.
- Prefer focused assertions on validation, parsing, and tool contracts over full LLM output checks.
- Use `pytest.raises` for expected validation failures (for example finance SQL that joins `receipts` with Splitwise views in one statement).
- Keep fixtures under `app/tests/fixtures/` when shared across modules.
