# Developer Runbook

How engineers work on Kirana day to day: where code lives, what runs locally, and which invariants the stack assumes. Facts below trace to `app/` source files.

## Repository layout

| Path | Role |
|---|---|
| `app/main.py` | FastAPI app, routes, and process lifespan (D1 client + `ChatService`). |
| `app/chat/` | LangGraph chat graph, SSE streaming, conversation SQLite, uploaded-image embedding. |
| `app/chat/gateway.py` | Cloudflare AI Gateway URL, auth headers, BYOK alias, `ChatOpenAI` construction. |
| `app/tools/` | Agent tools: D1 finance SQL (`finance.py`) and Vectorize + embedding cache (`vectorize.py`). |
| `app/ingestion/` | Receipt pipeline, embeddings, Cloudflare/Tigris/D1 helpers used by CLIs. |
| `app/utils/` | Config loading (`config.py`), D1 REST client (`db/d1.py`), logging helpers. |
| `app/setup.py` | Provisions D1, Vectorize, AI Gateway, Tigris (see [setup](./setup.md)). |
| `app/ingest_kb.py` | Splitwise CSV → D1 `splits`. |
| `app/ingest_receipts.py` | Receipt images → OCR, summaries, D1, Vectorize, Tigris. |
| `app/load_item_vectors.py` | Distinct `receipt_items.item_name` → item Vectorize index. |
| `app/bench.py` | HTTP benchmark client against the running API (see [evaluation](./evaluation.md)). |
| `docs/` | Architecture, API, data model, ingestion, setup, troubleshooting. |

`knowledge-base/` holds local sample receipts and exports for ingestion; it is gitignored for privacy.

## Local config

- **Single config file:** `app/config.toml` — models, Cloudflare resource names, ingestion knobs, paths. Loaded by `utils.config.load_config` from the process working directory (`app/` for normal commands).
- **Secrets:** `app/.env` — never committed. Required keys are listed in [setup](./setup.md#required-env).

Notable keys for debugging chat behavior:

- `[kirana].chat_db_path` — local SQLite for LangGraph checkpointer + `conversations` table (default `db.sqlite` under `app/`).
- `[kirana].receipt_image_match_threshold` — minimum Vectorize score before treating an item match as evidence for image questions (see `ChatService._message_with_uploaded_image_context` in `app/chat/service.py`).
- `[ingestion].embedding_model`, `[ingestion].embedding_dim` — must stay aligned with `[cloudflare].vectorize_index_dimension` (see [troubleshooting](./troubleshooting.md)).

## Typical developer workflow

1. `cd app && uv sync`
2. Copy `app/.env.example` to `app/.env` and fill credentials ([setup](./setup.md)).
3. `uv run python setup.py` when infrastructure is missing or schema/indexes need refresh.
4. Finish AI Gateway auth and provider keys in the dashboard before model-heavy commands.
5. Ingest data: `ingest_kb.py`, then `ingest_receipts.py`, then `load_item_vectors.py` ([ingestion](./ingestion.md)).
6. `uv run python main.py` — chat UI and API on port `8000`.

For a quick smoke test without Logfire:

```sh
cd app
KIRANA_DISABLE_LOGFIRE=1 uv run python main.py
```

## Tests and benchmarks

- **Unit tests:** from `app/`, run `uv run python -m pytest` (or target a file, e.g. `uv run python -m pytest tests/test_chat_service.py`).
- **Benchmarks:** require the server running in another shell; see [evaluation](./evaluation.md). `bench.py` uses the **first** entry in `[kirana].available_models` in `config.toml`, not the full list.

## Agent graph: two execution paths

The LangGraph graph is built in `ChatService._build_graph`: one `agent` node and one `tools` node with `tools_condition` routing (`app/chat/service.py`).

| Path | When | Behavior |
|---|---|---|
| **Standard OpenAI-compatible loop** | Model identifier is not treated as Gemini (`model_routes_via_gemini` in `app/chat/gateway.py` is false), or `tools_enabled` is false. | Agent node binds tools to the chat model, invokes with system + thread messages; LangGraph `ToolNode` runs tool calls; loop until no more tool calls. |
| **Gemini path** | Identifier contains `gemini` or `google-ai-studio`, and tools are enabled. | `_gemini_agent_response` runs up to three tool rounds: model requests tools, tools execute in-process, results appended; then a final synthesis call with a fixed human instruction not to call more tools. This avoids replaying Gemini function-call parts through the generic tool loop (see comment in [api](./api.md) for `POST /api/chat/stream`). |

Tool implementations are the same in both paths; only orchestration differs.

## Operational notes

- **In-process embedding cache:** `ChatService` holds `_embedding_cache` for text receipt queries and uploaded-image vectors. Restarting the server clears keys; see [troubleshooting](./troubleshooting.md#chat-and-api).
- **Rate limits:** LLM 429s retry with delays `(15, 30, 45, 60)` seconds (`RATE_LIMIT_RETRY_DELAYS_SECONDS` in `app/chat/service.py`). Gemini calls also respect `GeminiRateLimiter` using `[ingestion].gemini_min_interval_seconds`.
- **Logs:** `main.py` configures `loguru` and appends to `[kirana].chat_log_file`; Logfire spans are optional ([api](./api.md#observability)).

## Related docs

- [Architecture](./architecture.md) — components and retrieval flow diagram.
- [API](./api.md) — routes, SSE events, request fields.
- [Data model](./data-model.md) — D1, Vectorize, local SQLite.
- [Troubleshooting](./troubleshooting.md) — symptom tables.
