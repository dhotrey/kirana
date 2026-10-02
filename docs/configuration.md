# Configuration Reference

Kirana reads `app/config.toml` at startup through `app/utils/config.py`. Environment variables in `app/.env` are separate; see [setup](./setup.md#required-env).

The TOML section `[knowledge_base]` is loaded into the typed `Config.kb` field in Python (`KnowledgeBaseConfig`).

## `[kirana]`

| Key | Purpose |
|---|---|
| `log_level` | Loguru level for app and ingestion logging (`INFO`, `DEBUG`, etc.). Also copied to top-level `Config.log_level`. |
| `available_models` | Model aliases exposed by `GET /api/models` and the chat UI. |
| `model_identifiers` | Map from each alias to the Cloudflare AI Gateway OpenAI-compatible model id (for example `mistral/mistral-large-latest`). Every alias in `available_models` must have an entry. |
| `chat_db_path` | Local SQLite file for LangGraph checkpoints and the `conversations` table (default `db.sqlite`). |
| `chat_log_file` | Loguru sink for chat query/response metadata. |
| `receipt_vector_search_top_k` | Default `top_k` for `search_receipt_vectors` and `search_item_vectors` when the model omits it (1–100, default `8`). |
| `receipt_image_match_threshold` | Cosine-similarity floor the agent is instructed to apply for uploaded-image item matches (0–1, default `0.50`). Injected into image-upload user context in `ChatService`; not enforced inside the Vectorize tool itself. |

Benchmarks use the **first** alias in `available_models` (`app/bench.py`). There is no `--model` flag; reorder aliases or change the UI selection for other model comparisons.

## `[knowledge_base]`

| Key | Purpose |
|---|---|
| `splitwise_csv_path` | Path to the Splitwise export CSV consumed by `uv run python ingest_kb.py`. |

## `[cloudflare]`

| Key | Purpose |
|---|---|
| `d1_database_name` | D1 database name created or reused by `setup.py`. |
| `ai_gateway_name` | AI Gateway resource name (default `kirana-ai-gateway`). |
| `vectorize_index_name` | Receipt-summary Vectorize index (typo preserved: `kirana-reciept-summaries`). |
| `vectorize_item_index_name` | Item-name Vectorize index (`kirana-receipt-items`). |
| `vectorize_embedding_model` | Label recorded with the index; embeddings are produced locally with `Qwen/Qwen3-VL-Embedding-2B`. |
| `vectorize_index_dimension` | Vector dimension for both indexes (must match `[ingestion].embedding_dim`, default `1536`). |
| `vectorize_index_metadata_fields` / `vectorize_index_metadata_field_types` | Indexed metadata on the receipt-summary index (`receipt_id`, `store_name`, `date`). |
| `vectorize_item_index_metadata_fields` / `vectorize_item_index_metadata_field_types` | Indexed metadata on the item index (`item_name`). |

Runtime D1 and Vectorize calls also require `CLOUDFLARE_ACCOUNT_ID`, `CLOUDFLARE_API_TOKEN`, and `KIRANA_DB_ID` in `app/.env`.

## `[tigris]`

| Key | Purpose |
|---|---|
| `bucket_name` | S3-compatible bucket for raw receipt images and derived artifacts. |
| `aws_endpoint_url_s3` / `aws_endpoint_url_iam` / `aws_region` | Tigris endpoints used by ingestion and `setup.py`. |

Credentials: `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` in `app/.env`.

## `[ingestion]`

| Key | Purpose |
|---|---|
| `receipts_image_dir` | Default directory scanned by `ingest_receipts.py` when `--image` is not set. |
| `prompts_dir` | Directory for ingestion and default chat system prompt files (typically `app/prompts`). |
| `logs_dir` | Canonical ingestion logs and dry-run artifacts. |
| `gemini_model` / `mistral_model` | Gateway model ids for receipt OCR and summary generation. |
| `gemini_rpm` / `gemini_min_interval_seconds` | Client-side pacing for Gemini extraction calls. |
| `max_ocr_retries` | Application retries after validation failures (separate from gateway 5xx retries). |
| `retry_backoff_*` | Backoff between OCR retries (`constant`, `linear`, or `exponential`). |
| `sum_tolerance_pct` | Allowed percent drift between line items and receipt subtotal during validation. |
| `embedding_model` / `embedding_dim` | Local `SentenceTransformer` model and output dimension (`embedding_dim` must divide `1536`). |
| `embedding_image_max_dimension` | Longest-side resize before image embedding (chat uploads and ingestion). |
| `embedding_device` | Optional torch device for embeddings; empty uses the library default. |
| `dry_run` | Default dry-run flag for ingestion CLIs when `--dry-run` is not passed (normally `false`). |

See [ingestion](./ingestion.md) for how these keys affect the receipt and item-vector pipelines.
