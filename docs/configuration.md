# Configuration

Kirana reads `app/config.toml` at startup through `app/utils/config.py`, which validates values with Pydantic models in `app/utils/types.py`. Environment variables in `app/.env` are separate: they supply Cloudflare, Tigris, gateway, and Logfire credentials rather than replacing `config.toml`.

Run commands from `app/` so relative paths such as `db.sqlite`, `logs/`, and `../knowledge-base/` resolve correctly.

## `[kirana]`

Chat UI, logging, and retrieval tuning.

| Key | Type | Default (stock) | Used by | Description |
|---|---|---|---|---|
| `log_level` | string | `DEBUG` | `main.py`, ingestion CLIs | Loguru level for app and ingestion logs. |
| `available_models` | list of strings | `mistral`, `gemini-3.1-flash` | `GET /api/models`, `bench.py` | Model aliases exposed in the chat UI and benchmarks. |
| `model_identifiers` | map alias → gateway model ID | see `config.toml` | `chat/gateway.py`, benchmarks | Cloudflare AI Gateway model identifiers, including provider prefix (for example `mistral/...`, `google-ai-studio/...`). Every alias in `available_models` must have an entry. |
| `chat_db_path` | string | `db.sqlite` | `chat/service.py` | Local SQLite file for `conversations` and LangGraph checkpoints. |
| `chat_log_file` | string | `logs/chat.log` | `main.py` | Rotating Loguru sink for chat request/response logs. |
| `receipt_vector_search_top_k` | int (1–100) | `8` | `tools/vectorize.py` | Default `top_k` for `search_receipt_vectors` when the model omits it. |
| `receipt_image_match_threshold` | float (0–1) | `0.50` | `chat/service.py`, `tools/vectorize.py` | Minimum Vectorize similarity score before treating an uploaded-image match as evidence. Injected into image-upload user messages and enforced in `search_item_vectors`. |

## `[knowledge_base]`

| Key | Type | Default (stock) | Used by | Description |
|---|---|---|---|---|
| `splitwise_csv_path` | string | `../knowledge-base/splitwise/...` | `ingest_kb.py` | Path to the Splitwise export CSV imported into D1 `splits`. |

## `[cloudflare]`

Remote resource names and Vectorize index shape. Must stay aligned with what `setup.py` provisions.

| Key | Type | Default (stock) | Used by | Description |
|---|---|---|---|---|
| `d1_database_name` | string | `kirana` | `setup.py`, D1 client | Cloudflare D1 database name. |
| `ai_gateway_name` | string | `kirana-ai-gateway` | `setup.py`, `chat/gateway.py` | AI Gateway resource name for chat and ingestion model calls. |
| `vectorize_index_name` | string | `kirana-reciept-summaries` | ingestion, `tools/vectorize.py` | Receipt-summary Vectorize index (semantic trip retrieval). |
| `vectorize_item_index_name` | string | `kirana-receipt-items` | `load_item_vectors.py`, `tools/vectorize.py` | Item-name Vectorize index (uploaded-image and fuzzy item matching). |
| `vectorize_embedding_model` | string | `qwen3-vl-embedding-2b` | `setup.py` | Embedding model label stored with the Vectorize index metadata. |
| `vectorize_index_dimension` | int | `1536` | setup, chat, tools | Vector dimension for both indexes. Must match `[ingestion].embedding_dim`. |
| `vectorize_index_metadata_fields` | list | `receipt_id`, `store_name`, `date` | `setup.py` | Metadata fields indexed on the receipt-summary index. |
| `vectorize_index_metadata_field_types` | list | `number`, `string`, `number` | `setup.py` | Types for receipt-summary metadata indices. `date` is numeric `YYYYMMDD`. |
| `vectorize_item_index_metadata_fields` | list | `item_name` | `setup.py` | Metadata fields on the item index. |
| `vectorize_item_index_metadata_field_types` | list | `string` | `setup.py` | Types for item-index metadata. |

## `[tigris]`

S3-compatible object storage for receipt images and derived artifacts.

| Key | Type | Default (stock) | Used by | Description |
|---|---|---|---|---|
| `bucket_name` | string | `kirana-kb-raw-data` | `setup.py`, ingestion | Tigris bucket for raw and derived receipt files. |
| `aws_endpoint_url_s3` | string | `https://t3.storage.dev` | `setup.py`, ingestion | S3 API endpoint. |
| `aws_endpoint_url_iam` | string | `https://iam.storage.dev` | config only | IAM endpoint (documented for Tigris tooling). |
| `aws_region` | string | `auto` | `setup.py`, ingestion | AWS region passed to boto3 clients. |

## `[ingestion]`

Receipt ingestion, local embeddings, and ingestion-side rate limiting.

| Key | Type | Default (stock) | Used by | Description |
|---|---|---|---|---|
| `receipts_image_dir` | string | `../knowledge-base/receipts/images` | `ingest_receipts.py` | Directory scanned when `--image` is not passed. |
| `prompts_dir` | string | `prompts` | ingestion, chat | Directory for `system_prompt.md`, receipt extraction prompts, and benchmark overrides such as `system_icl.md`. |
| `logs_dir` | string | `logs` | ingestion | Canonical per-receipt logs and dry-run artifacts. |
| `gemini_model` | string | `google-ai-studio/gemini-3.1-flash-lite-preview` | `ingestion/context.py` | Gateway model ID for receipt OCR extraction. |
| `mistral_model` | string | `mistral/mistral-large-latest` | `ingestion/context.py` | Gateway model ID for receipt summary generation. |
| `gemini_rpm` | int (≥1) | `5` | ingestion rate limiter | Documented RPM budget for Gemini ingestion calls. |
| `gemini_min_interval_seconds` | float (>0) | `12.0` | ingestion and chat (`ChatService`) | Minimum spacing between Gemini-routed calls to reduce 429s. |
| `max_ocr_retries` | int (≥0) | `3` | `ingestion/gemini.py` | Max extraction/validation retries per receipt image. |
| `retry_backoff_strategy` | `constant` \| `linear` \| `exponential` | `exponential` | ingestion LLM utils | Backoff strategy for ingestion model retries. |
| `retry_backoff_base_seconds` | float (≥0) | `1.0` | ingestion LLM utils | Initial backoff delay. |
| `retry_backoff_max_seconds` | float (≥0) | `30.0` | ingestion LLM utils | Cap on backoff delay. |
| `sum_tolerance_pct` | float (≥0) | `5.0` | receipt validation | Allowed percent drift between line-item sum and receipt subtotal. |
| `embedding_model` | string | `Qwen/Qwen3-VL-Embedding-2B` | ingestion, chat, tools | Local SentenceTransformer model for summaries, item names, and uploaded images. |
| `embedding_dim` | int (1–1536) | `1536` | ingestion, chat, tools | Output dimension; must divide 1536 and match `vectorize_index_dimension`. |
| `embedding_image_max_dimension` | int (>0) | `256` | ingestion, chat | Longest-side resize before image embedding (no upscaling). |
| `embedding_device` | string or empty | `""` | ingestion, chat | Optional `SentenceTransformer` device; empty uses the library default. |
| `dry_run` | bool | `false` | ingestion context | Default dry-run flag (CLI `--dry-run` overrides per run). |

## Environment variables (not in `config.toml`)

These live in `app/.env`. See [setup](./setup.md#required-env).

| Variable | Required when | Purpose |
|---|---|---|
| `CLOUDFLARE_API_TOKEN` | setup, ingestion, chat tools | Cloudflare API access for D1 and Vectorize. |
| `CLOUDFLARE_ACCOUNT_ID` | setup, gateway, D1, Vectorize | Account ID embedded in gateway and D1 URLs. |
| `CLOUDFLARE_AI_GATEWAY_API_TOKEN` | chat, ingestion models | `cf-aig-authorization` header for Authenticated Gateway. |
| `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` | setup, ingestion | Tigris S3 credentials. |
| `KIRANA_DB_ID` | after D1 exists | D1 database UUID; `setup.py` appends on first create. |
| `LOGFIRE_TOKEN` | tracing enabled | Logfire write token. |
| `KIRANA_DISABLE_LOGFIRE` | optional | Set to `1`, `true`, or `yes` to disable Logfire. |

## Constraints worth preserving

- **Embedding alignment**: `[ingestion].embedding_dim` must equal `[cloudflare].vectorize_index_dimension`. Changing one without re-embedding and re-upserting breaks Vectorize search.
- **Model aliases**: Add new chat models to both `available_models` and `model_identifiers`, and configure the matching AI Gateway provider key.
- **Gemini chat models**: Identifiers containing `gemini` or `google-ai-studio` use the in-agent tool loop in `ChatService` rather than LangGraph `ToolNode` ([architecture](./architecture.md#model-routing-and-tool-execution)).
- **Offline embeddings**: `main.py` sets `HF_HUB_OFFLINE=1` at import. Pre-download embedding weights before relying on chat or ingestion on an air-gapped machine ([troubleshooting](./troubleshooting.md)).
