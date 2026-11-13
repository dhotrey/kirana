# Testing

Kirana uses `pytest` for fast, offline unit tests under `app/tests/`. Tests validate SQL guardrails, ingestion schemas, vectorize helpers, and chat service behavior without requiring a running FastAPI server, Cloudflare credentials, or a populated knowledge base.

## Running tests

From `app/` after `uv sync`:

```sh
cd app
uv run pytest
```

Useful variants:

```sh
uv run pytest -q                    # quiet summary
uv run pytest tests/test_chat_tools.py
uv run pytest -k "finance_sql"
```

`[tool.pytest.ini_options]` in `app/pyproject.toml` sets `pythonpath = ["."]`, so imports resolve the same way as `uv run python main.py`.

## What is covered (by module)

| Area | Test modules | What they assert |
|---|---|---|
| Chat graph and streaming helpers | `test_chat_service.py` | Rate-limit retry backoff, conversation metadata, Gemini vs. non-Gemini paths where mocked. |
| Finance SQL tool | `test_chat_tools.py` | `validate_finance_sql` allow/deny rules, expense views, receipt vs. Splitwise combination guard. |
| D1 setup DDL | `test_db_setup.py` | Schema strings and expense views match `app/utils/db/db_setup.py`. |
| Embeddings | `test_embeddings.py`, `test_embedding_benchmark.py` | Embedding prep/encode helpers; benchmark image path is skipped when fixtures are absent. |
| Item / receipt Vectorize | `test_items_vectorize.py`, `test_setup_vectorize.py`, `test_vectorize_tools.py` | Index metadata, tool JSON shapes, mock Vectorize clients. |
| Ingestion pipeline | `test_ingestion_*.py`, `test_ingest_kb.py` | Schemas, prompts, rate limiting, sources, D1 writers, observability toggles. |

Integration-style checks (live gateway, D1, Vectorize) are intentionally out of scope for pytest. Use [setup](./setup.md), ingestion CLIs, and [evaluation](./evaluation.md) benchmarks against a running `main.py` for end-to-end validation.

## CI and local expectations

- Target: all tests pass; one test may skip when optional benchmark images are missing (`test_embedding_benchmark.py`).
- Tests do not load the Hugging Face embedding weights unless a case explicitly constructs an `Embedder` with local fixtures.
- Set `KIRANA_DISABLE_LOGFIRE=1` in the environment when debugging tests that touch observability helpers if Logfire is not configured.

## Adding tests

When changing tool contracts, SQL validation, or ingestion schemas:

1. Add or extend a focused test beside related cases in `app/tests/`.
2. Prefer mocks/stubs for Cloudflare and model clients; keep tests deterministic.
3. Run `uv run pytest` from `app/` before opening a PR (see [AGENTS.md](../AGENTS.md)).
