# Testing

Kirana uses `pytest` from the `app/` environment. Tests are unit and integration checks for ingestion, chat tools, SQL validation, embeddings, and setup helpers. They do not require a running FastAPI server, provisioned Cloudflare resources, or ingested knowledge-base data unless a test explicitly mocks those dependencies.

## Run tests

From `app/`:

```sh
uv sync
uv run pytest
```

Run a focused file or test name:

```sh
uv run pytest tests/test_chat_tools.py
uv run pytest tests/test_vectorize_tools.py -k search_item_vectors
```

Verbose output with local variable traces on failure:

```sh
uv run pytest -vv
```

## What the suite covers

| Area | Representative files | Behavior checked |
|---|---|---|
| Chat service and tools | `tests/test_chat_service.py`, `tests/test_chat_tools.py` | LangGraph wiring, Gemini in-agent tool loop, tool stats extraction, streaming helpers |
| Finance SQL validation | `tests/test_chat_tools.py` | Read-only `SELECT` rules, forbidden statements, receipt vs. Splitwise table separation |
| Vectorize tools | `tests/test_vectorize_tools.py` | Embedding cache keys, metadata filter normalization, item vs. receipt search inputs |
| Ingestion pipeline | `tests/test_ingestion_*.py`, `tests/test_ingest_kb.py` | Receipt schemas, D1 writes, rate limiting, canonical logs, Splitwise import |
| Embeddings and vectors | `tests/test_embeddings.py`, `tests/test_items_vectorize.py` | Local Qwen embedding dimensions and item-vector ID generation |
| Setup helpers | `tests/test_db_setup.py`, `tests/test_setup_vectorize.py` | D1 schema/index creation and Vectorize metadata index definitions |

## Relationship to benchmarks

`uv run pytest` exercises deterministic Python modules and mocked I/O. `uv run python bench.py` is an end-to-end evaluation against a live local server and ingested data. Use pytest while changing tool validation, ingestion helpers, or chat routing; use benchmarks when comparing model and retrieval behavior on the full knowledge base.

## Common pitfalls

- Run commands from `app/` so `pythonpath = ["."]` in `pyproject.toml` resolves package imports.
- `main.py` sets `HF_HUB_OFFLINE=1` at import time for the server, but most tests mock embedders or avoid loading weights. If an embedding test fails on a clean machine, populate the Hugging Face cache once before running offline.
- Tests must not read from or write to `app/.venv/`, committed secrets, or private `knowledge-base/` exports.
