# Testing

Kirana uses `pytest` for unit and integration-style tests. Tests live under `app/tests/` and run against local Python modules without requiring a live FastAPI server, Cloudflare credentials, or ingested data.

## Running Tests

From `app/`:

```sh
uv sync
uv run pytest
```

Useful variants:

```sh
uv run pytest -q                    # quiet summary
uv run pytest tests/test_chat_tools.py -k splitwise
uv run pytest --tb=short            # shorter tracebacks on failure
```

The stock suite is fast and offline-friendly. As of August 2026 it reports **82 passed, 1 skipped**.

## Layout

| Path | Covers |
|---|---|
| `tests/test_chat_service.py` | Rate-limit detection/retry, tool-name extraction for SSE stats, Gemini-adjacent helpers. |
| `tests/test_chat_tools.py` | `query_finance_db` SQL validation, D1 response parsing helpers. |
| `tests/test_vectorize_tools.py` | Receipt and item Vectorize search tools, embedding cache keys, metadata filters. |
| `tests/test_db_setup.py` | D1 schema/index DDL emitted by `app/utils/db/db_setup.py`. |
| `tests/test_setup_vectorize.py` | Vectorize index creation helpers used by `setup.py`. |
| `tests/test_ingestion_*.py` | Receipt pipeline modules: schemas, prompts, Gemini/Mistral adapters, D1 writes, rate limits, observability, canonical logs, disk/upload sources. |
| `tests/test_ingest_kb.py` | Splitwise CSV import into `splits`. |
| `tests/test_embeddings.py` | Local Qwen embedding helpers and image prep. |
| `tests/test_items_vectorize.py` | Item-name vector upsert logic for `load_item_vectors.py`. |
| `tests/test_embedding_benchmark.py` | Optional local image-embedding benchmark (skipped by default). |

`pythonpath` is set to `app/` in `pyproject.toml`, so imports match runtime modules (`chat`, `ingestion`, `tools`, `utils`).

## What Is Mocked

Most tests avoid network I/O:

- Finance and Vectorize tools are tested with validation logic and stubbed Cloudflare clients.
- Chat service tests patch LangChain model invocations to exercise retry and message-stat helpers.
- Ingestion tests use fixtures such as `tests/fixtures/receipt.json` and mocked gateway responses.

No test currently boots `uv run python main.py` or calls the streaming HTTP API. End-to-end query-family checks live in `app/bench.py` against a running server ([evaluation](./evaluation.md)).

## Skipped / Opt-In Tests

`tests/test_embedding_benchmark.py` is skipped unless:

```sh
KIRANA_RUN_IMAGE_EMBED_BENCHMARK=1 uv run pytest tests/test_embedding_benchmark.py
```

It also skips when `knowledge-base/images/` has no sample images. Use this only for local embedding latency experiments, not CI.

## Logfire During Tests

Some chat tests touch code paths that emit Logfire spans. If `LOGFIRE_TOKEN` is unset, pytest may print a `LogfireNotConfiguredWarning`. This does not fail the suite. For clean output locally, either configure Logfire or set:

```sh
KIRANA_DISABLE_LOGFIRE=1 uv run pytest
```

## Adding Tests

Follow existing patterns:

- Put focused tests beside the subsystem they protect (`test_ingestion_d1.py` for `ingestion/d1.py`, etc.).
- Prefer deterministic assertions on validation, SQL normalization, and parsed payloads over live API calls.
- When changing finance SQL rules in `app/tools/finance.py`, extend `tests/test_chat_tools.py`.
- When changing Vectorize tool contracts, extend `tests/test_vectorize_tools.py`.

Run the narrowest file before opening a PR:

```sh
uv run pytest tests/test_chat_tools.py tests/test_vectorize_tools.py
```
