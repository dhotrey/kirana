# Testing

Kirana uses `pytest` for unit and integration tests. Tests live under `app/tests/` and run against the same modules the app imports at runtime (`chat/`, `tools/`, `ingestion/`, `utils/`).

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
uv run pytest -k finance                # name filter
```

`app/pyproject.toml` sets `pythonpath = ["."]`, so imports resolve the same way as `uv run python main.py`.

## Current Suite Shape

As of September 2026 the suite reports **82 passed, 1 skipped**.

| Area | Modules | What they cover |
|---|---|---|
| Chat | `test_chat_service.py`, `test_chat_tools.py` | Rate-limit retry helpers, tool-name extraction, finance SQL validation |
| Tools | `test_vectorize_tools.py` | Receipt/item vector search helpers, embedding cache keys, config thresholds |
| Ingestion | `test_ingestion_*.py`, `test_ingest_kb.py`, `test_items_vectorize.py` | Pipeline schemas, prompts, D1 writes, Gemini/Mistral paths, rate limiting, observability |
| Storage | `test_db_setup.py`, `test_setup_vectorize.py` | D1 schema creation, Vectorize index metadata |
| Embeddings | `test_embeddings.py`, `test_embedding_benchmark.py` | Local embedder behavior; optional image benchmark |

## Optional Benchmark Test

`test_embed_local_knowledge_base_images_benchmark` is skipped unless:

```sh
KIRANA_RUN_IMAGE_EMBED_BENCHMARK=1 uv run pytest tests/test_embedding_benchmark.py
```

It also needs sample images under `knowledge-base/images/`. This is a local timing harness, not a CI gate.

## Environment Notes

- Most tests mock Cloudflare, gateway, and database calls. They do not require provisioned D1, Vectorize, or Tigris resources.
- Logfire may emit `LogfireNotConfiguredWarning` during chat-service tests when `LOGFIRE_TOKEN` is unset. For local runs, either configure Logfire or set `KIRANA_DISABLE_LOGFIRE=1`.
- `main.py` sets `HF_HUB_OFFLINE=1` at import time. Embedding-related tests that load `Qwen/Qwen3-VL-Embedding-2B` expect the model weights to already be cached locally.

## Before Finishing Code Changes

Run the narrowest relevant check:

```sh
cd app
uv run pytest tests/test_<affected_area>.py
```

For broad chat, tool, or ingestion edits, run the full suite with `uv run pytest`.
