# Testing

Kirana uses `pytest` from the `app/` project. Tests are offline-friendly: they mock Cloudflare APIs, gateway calls, and heavy embedding loads unless a case explicitly exercises local model code.

## Run the suite

```sh
cd app
uv sync
uv run pytest
```

Useful variants:

```sh
uv run pytest tests/test_chat_service.py -q
uv run pytest -k finance -q
```

As of October 2026 the suite reports **82 passed, 1 skipped** on a clean `uv sync`.

## Layout

| Module prefix | Covers |
|---|---|
| `test_chat_service.py` | LangGraph chat service, Gemini in-agent tool loop, rate-limit retries, conversation persistence helpers. |
| `test_chat_tools.py`, `test_vectorize_tools.py` | Registered finance and Vectorize tool behavior and validation. |
| `test_db_setup.py`, `test_ingestion_d1.py` | D1 schema setup and ingestion persistence. |
| `test_ingestion_*.py` | Receipt pipeline pieces: Gemini/Mistral prompts, schemas, rate limits, sources, observability, canonical logs. |
| `test_embeddings.py`, `test_items_vectorize.py`, `test_setup_vectorize.py` | Local Qwen embedding helpers and Vectorize index setup. |
| `test_ingest_kb.py` | Splitwise CSV import. |
| `test_embedding_benchmark.py` | Benchmark harness utilities (not the full `bench.py` integration). |

Fixtures live under `app/tests/fixtures/` (for example `receipt.json`).

## Related checks

- Smoke the HTTP app: `uv run python main.py` (see [setup](./setup.md)).
- End-to-end agent benchmarks require a running server; see [evaluation](./evaluation.md) and [app/utils/benchmarks/README.md](../app/utils/benchmarks/README.md).
