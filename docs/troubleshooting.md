# Troubleshooting

Symptoms and fixes for local Kirana development. All behavior below is grounded in `app/main.py`, `app/chat/service.py`, and ingestion entrypoints unless noted.

## Chat and API

| Symptom | Likely cause | What to do |
|--------|----------------|------------|
| Assistant says finance or vector tools failed | Missing or invalid Cloudflare env (`CLOUDFLARE_ACCOUNT_ID`, `CLOUDFLARE_API_TOKEN`, `KIRANA_DB_ID`) or gateway auth | Confirm `app/.env` matches [setup](./setup.md). Chat still streams when D1 is misconfigured; tool JSON returns `ok: false` with an error string. |
| `Unknown embedding_key` from vector tools | Server restart or different process than the one that created the key | Embedding vectors live in an in-process dict in `ChatService` (`app/chat/service.py`). Start a new chat turn after restart; for text queries call `embed_receipt_query` again before `search_receipt_vectors`. |
| Uploaded-image answers feel random or always "no" | Item index empty or threshold too strict | Run `uv run python load_item_vectors.py` after receipts exist ([ingestion](./ingestion.md)). Tune `[kirana].receipt_image_match_threshold` in `app/config.toml` (default `0.50`). |
| Image upload rejected | Empty body, wrong MIME type, or over 10 MB | `ChatService` requires non-empty bytes, optional `image/*` content type check when provided, and `MAX_IMAGE_UPLOAD_BYTES` (`app/chat/service.py`). |
| Rate-limit SSE events but then failure | Upstream 429 persisted after backoff | Retries use 15s, 30s, 45s, 60s delays (`RATE_LIMIT_RETRY_DELAYS_SECOND`). Reduce concurrency or switch model alias; Gemini routes also wait `gemini_min_interval_seconds` before calls (`app/config.toml`). |
| Plain-LLM baseline still uses tools in traces | Request flag | Send `tools_enabled: false` on `/api/chat/stream` and `/api/chat/image/stream` ([api](./api.md)). |
| Gemini answers stop after tools without a final narrative | Internal tool round cap | Gemini routing executes tools inside the agent node for at most **three** tool-request rounds, then forces a synthesis prompt (`app/chat/service.py`). If a task needs more hops, narrow the question or split the thread. |
| `bench.py` only exercised QF-1 | Default family selection | With no `--QF2` / `--QF3` / `--QF4` / `--all`, `bench.py` runs **QF-1 only** ([evaluation](./evaluation.md#cli-behavior-appbenchpy)). |

## Models and local embeddings

| Symptom | Likely cause | What to do |
|--------|----------------|------------|
| First chat or ingest run fails loading `Qwen/...` | `main.py` sets `HF_HUB_OFFLINE=1` at import | Ensure embedding model weights are already present in the Hugging Face cache for this machine, or run once with network access from a helper process to populate the cache before relying on offline mode. |
| `Image vector dimension does not match` | Config drift | Keep `[ingestion].embedding_dim` aligned with `[cloudflare].vectorize_index_dimension` (both `1536` in the stock `config.toml`). |

## Ingestion and data

| Symptom | Likely cause | What to do |
|--------|----------------|------------|
| Receipt ingestion fails on models | AI Gateway not finished | Complete Authenticated Gateway and provider keys before `ingest_receipts.py` ([setup](./setup.md#finish-cloudflare-ai-gateway-setup)). |
| Splitwise import errors | Wrong CSV path or schema | Check `[knowledge_base].splitwise_csv_path` in `app/config.toml` points at a real export file. The importer uses **fixed 0-based column indices** for money fields (`cost` column index `3`, `me` `5`, roommate columns `6` and `7` in `app/ingest_kb.py`); exports with different column order need preprocessing. |
| Semantic receipt search returns nothing | Summaries not embedded or wrong index | Run full `ingest_receipts.py` pipeline; confirm index name `kirana-reciept-summaries` in config matches Vectorize. |

## Operational pitfalls

- **UI works, answers do not**: Starting `uv run python main.py` without setup, gateway keys, or ingestion is expected to yield empty or tool-error-backed replies ([README](../README.md#get-running)).
- **Logfire noise or failures**: Set `KIRANA_DISABLE_LOGFIRE=1` for local smoke tests, or provide `LOGFIRE_TOKEN` before long ingestion runs ([setup](./setup.md#logfire-setup)).
- **Do not commit secrets or private exports**: Keep `app/.env`, `db.sqlite`, logs, and `knowledge-base/` out of version control per project rules.
