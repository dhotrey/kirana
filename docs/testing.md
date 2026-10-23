# Testing

Kirana uses `pytest` for unit and integration tests under `app/tests/`. Tests run locally with the `app/` virtual environment managed by `uv`; they do not start the FastAPI server or call live Cloudflare APIs unless a test explicitly mocks those clients.

## Run the suite

From `app/`:

```sh
uv sync
uv run pytest
```

Run a single file or test:

```sh
uv run pytest tests/test_chat_tools.py
uv run pytest tests/test_chat_tools.py -k combine_receipts
```

Quiet summary:

```sh
uv run pytest -q
```

## What is covered

| Area | Example modules | Notes |
|---|---|---|
| Chat agent | `test_chat_service.py` | LangGraph wiring, Gemini tool-loop behavior, rate-limit retry helper |
| Finance SQL tool | `test_chat_tools.py` | `validate_finance_sql` allow/deny rules, including receipt vs. Splitwise separation |
| Vectorize tools | `test_vectorize_tools.py` | Receipt and item search tool contracts |
| D1 setup | `test_db_setup.py` | Schema DDL matches documented tables and views |
| Ingestion | `test_ingestion_*.py`, `test_ingest_kb.py` | Pipeline schemas, prompts, rate limits, sources, Gemini/Mistral helpers |
| Embeddings | `test_embeddings.py`, `test_items_vectorize.py` | Local Qwen embedding paths and Vectorize payload shape |

Fixtures such as `app/tests/fixtures/receipt.json` support ingestion schema tests without reading private `knowledge-base/` files from git.

## Logfire and local runs

Some chat tests exercise code paths that open Logfire spans. If Logfire is not configured, pytest may emit a `LogfireNotConfiguredWarning`; this does not fail the suite. For a clean local run, either set `LOGFIRE_TOKEN` in `app/.env` or export `KIRANA_DISABLE_LOGFIRE=1` before `uv run pytest`.

## Before merging behavior changes

When changing chat tools, ingestion, or D1 schema:

1. Add or update tests in the matching `app/tests/test_*.py` module.
2. Run `uv run pytest` from `app/`.
3. Update the relevant doc under `docs/` (API, architecture, data model, or ingestion) in the same change when public behavior shifts.
