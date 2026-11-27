# Testing

Kirana uses [pytest](https://docs.pytest.org/) from the `app/` package. Tests are fast, offline-friendly unit checks around chat tools, ingestion helpers, D1 parsing, embeddings, and setup scripts. They do not hit Cloudflare APIs unless a test explicitly mocks HTTP.

## Running tests

From `app/`:

```sh
uv sync
uv run pytest
```

Useful variants:

```sh
uv run pytest app/tests/test_chat_tools.py -q
uv run pytest -k validate_finance_sql -q
```

Pytest is configured in `app/pyproject.toml` with `pythonpath = ["."]`, so imports match runtime (`from chat.service import ...`, `from tools.finance import ...`).

## Layout

| Module | What it covers |
|---|---|
| `test_chat_service.py` | Rate-limit retry timing, conversation helpers, and chat service edge behavior. |
| `test_chat_tools.py` | `validate_finance_sql` allow/deny rules, including receipt vs. Splitwise separation and unsafe SQL rejection; D1 row extraction helpers. |
| `test_db_setup.py` | D1 schema/setup SQL emitted by `app/utils/db/db_setup.py`. |
| `test_vectorize_tools.py` | Receipt and item Vectorize tool wiring and filter behavior. |
| `test_embeddings.py`, `test_items_vectorize.py`, `test_setup_vectorize.py` | Local embedding dimensions and Vectorize index setup assumptions. |
| `test_ingest_kb.py`, `test_ingestion_*.py` | Ingestion pipeline modules: schemas, prompts, rate limits, canonical logging, Gemini helpers, disk/upload sources. |
| `test_embedding_benchmark.py` | Embedding benchmark harness smoke checks. |

Fixtures for structured receipt JSON live under `app/tests/fixtures/`.

## Relationship to evaluation

- **pytest**: deterministic module-level checks; safe to run in CI without API keys beyond what each test mocks.
- **`app/bench.py`**: end-to-end query-family benchmarks against a live `main.py` server and real D1/Vectorize data ([evaluation](./evaluation.md)).

Before finishing doc or tool changes, run the narrowest pytest slice that touches your edit; for broad chat or finance tool edits, run the full suite.

## Smoke check

`AGENTS.md` also recommends `uv run python main.py` as an app skeleton smoke test. That starts the FastAPI server; pytest does not replace a manual chat or benchmark run when validating retrieval quality.