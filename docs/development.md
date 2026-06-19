# Development Guide

Local development workflow for the Kirana app under `app/`. All commands below assume the current working directory is `app/`.

## Codebase Layout

| Path | Role |
|---|---|
| `main.py` | FastAPI entrypoint, route handlers, app lifespan (D1 client, chat service, Logfire). Sets `HF_HUB_OFFLINE=1` at import so embedding weights must already be cached locally. |
| `setup.py` | One-shot infrastructure provisioning for D1, Vectorize, AI Gateway, and Tigris. |
| `ingest_kb.py` | Splitwise CSV import into D1 `splits`. |
| `ingest_receipts.py` | Receipt image ingestion CLI; delegates to `ingestion/`. |
| `load_item_vectors.py` | Embeds distinct `receipt_items.item_name` values into the item Vectorize index. |
| `bench.py` | Benchmark CLI over the streaming chat API. |
| `config.toml` | Typed runtime configuration loaded by `utils/config.py`. |
| `chat/` | LangGraph chat graph, SSE streaming, conversation SQLite persistence, Cloudflare AI Gateway model wiring. |
| `tools/` | Agent tools: validated D1 SQL (`finance.py`) and Vectorize retrieval (`vectorize.py`). |
| `ingestion/` | Receipt extraction, validation, summary, embedding, D1/Vectorize/Tigris writes, observability. |
| `utils/db/` | D1 HTTP client and schema DDL used by `setup.py`. |
| `utils/benchmarks/` | HTTP client harness for benchmark and evaluation scripts. |
| `tests/` | Pytest unit tests for ingestion, tools, chat, and setup helpers. |
| `prompts/` | System and ingestion prompt templates (`system_prompt.md`, `receipt_extraction.md`, etc.). |

Data that stays out of git: `app/.env`, `db.sqlite`, `logs/`, local embedding caches, and everything under `knowledge-base/`.

## Running Tests

Install dependencies and run the full suite:

```sh
uv sync
uv run pytest
```

Useful variants:

```sh
uv run pytest tests/test_chat_tools.py -q
uv run pytest tests/test_vectorize_tools.py -v
```

The suite is offline-friendly for most modules. Tests that exercise chat rate-limit retry logic may emit a Logfire-not-configured warning when `LOGFIRE_TOKEN` is unset; that does not fail the run. Set `KIRANA_DISABLE_LOGFIRE=1` to skip Logfire export during local runs.

As of the current tree, expect roughly 80+ passing tests with a small number of skips for environment-specific cases.

## Configuration Reference

Configuration is loaded from `app/config.toml` into the typed `Config` model in `app/utils/types.py`. The TOML section `[knowledge_base]` maps to the internal `kb` field.

### `[kirana]`

| Key | Purpose |
|---|---|
| `log_level` | Loguru level for stderr and the chat logfile. |
| `available_models` | Model aliases exposed by `GET /api/models` and the chat UI. |
| `model_identifiers` | Maps each alias to a Cloudflare AI Gateway provider/model path. |
| `chat_db_path` | Local SQLite path for conversations and LangGraph checkpoints. |
| `chat_log_file` | Rotating Loguru file for chat request/response logs. |
| `receipt_vector_search_top_k` | Default `top_k` for `search_receipt_vectors` and `search_item_vectors` (1–100). |
| `receipt_image_match_threshold` | Injected into uploaded-image chat turns; the agent should treat Vectorize scores below this as non-matches (default `0.50`). |

### `[knowledge_base]`

| Key | Purpose |
|---|---|
| `splitwise_csv_path` | Splitwise export CSV consumed by `ingest_kb.py`. |

### `[cloudflare]`

| Key | Purpose |
|---|---|
| `d1_database_name` | D1 database name created or reused by `setup.py`. |
| `ai_gateway_name` | AI Gateway resource name. |
| `vectorize_index_name` | Receipt-summary Vectorize index (`kirana-reciept-summaries`). |
| `vectorize_item_index_name` | Item-name Vectorize index (`kirana-receipt-items`). |
| `vectorize_embedding_model` | Cloudflare-side embedding model label for the index. |
| `vectorize_index_dimension` | Vector dimension (must match `[ingestion].embedding_dim`). |
| `vectorize_index_metadata_fields` / `vectorize_index_metadata_field_types` | Receipt-summary metadata indices (`receipt_id`, `store_name`, `date`). |
| `vectorize_item_index_metadata_fields` / `vectorize_item_index_metadata_field_types` | Item index metadata (`item_name`). |

### `[tigris]`

| Key | Purpose |
|---|---|
| `bucket_name` | Raw receipt image bucket. |
| `aws_endpoint_url_s3` / `aws_endpoint_url_iam` / `aws_region` | S3-compatible endpoints for Tigris. |

### `[ingestion]`

| Key | Purpose |
|---|---|
| `receipts_image_dir` | Default directory scanned by `ingest_receipts.py`. |
| `prompts_dir` | Prompt templates for extraction and chat. |
| `logs_dir` | Canonical ingestion logs and dry-run artifacts. |
| `gemini_model` / `mistral_model` | Hosted models for OCR and receipt summarization. |
| `gemini_rpm` / `gemini_min_interval_seconds` | Ingestion rate limits; chat Gemini routes reuse the min interval. |
| `max_ocr_retries` | Extraction/validation retry cap per receipt image. |
| `retry_backoff_*` | Backoff for gateway/network retries during ingestion. |
| `sum_tolerance_pct` | Allowed line-item sum drift vs. receipt subtotal during validation. |
| `embedding_model` / `embedding_dim` | Local SentenceTransformer model and output dimension (`embedding_dim` must divide 1536). |
| `embedding_image_max_dimension` | Longest-side resize cap before image embedding (chat uploads use the same setting). |
| `embedding_device` | Optional SentenceTransformer device string; empty uses the library default. |
| `dry_run` | Default dry-run flag for ingestion CLIs when `--dry-run` is not passed. |

## Environment Variables

See [setup](./setup.md#required-env) for required Cloudflare, Tigris, gateway, and Logfire credentials.

| Variable | When needed |
|---|---|
| `KIRANA_DISABLE_LOGFIRE` | Set to `1`, `true`, or `yes` to skip Logfire export locally. |
| `KIRANA_DB_ID` | Required after D1 exists; written by `setup.py` on first create. |

Chat and ingestion also require `CLOUDFLARE_ACCOUNT_ID`, `CLOUDFLARE_API_TOKEN`, and `CLOUDFLARE_AI_GATEWAY_API_TOKEN` at runtime when tools or hosted models are used.

## Local Smoke Check

After `uv sync`, a minimal app boot check:

```sh
KIRANA_DISABLE_LOGFIRE=1 uv run python main.py
```

The server starts on port 8000 with reload enabled. Grocery finance answers still require completed setup, gateway provider keys, and ingestion; see [troubleshooting](./troubleshooting.md).
