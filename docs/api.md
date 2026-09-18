# API Endpoints

The FastAPI application is served from `app/main.py`. When the local server is running, FastAPI exposes the live OpenAPI schema and Swagger UI:

- Swagger UI: `http://127.0.0.1:8000/docs`
- ReDoc: `http://127.0.0.1:8000/redoc`
- OpenAPI JSON: `http://127.0.0.1:8000/openapi.json`

Run the app from `app/`:

```sh
uv run python main.py
```

The chat API is a local, single-user prototype API. Conversation history is persisted in `db.sqlite` using LangGraph's SQLite checkpointer keyed by `thread_id`; sidebar metadata is stored in the `conversations` table in the same database.

## `GET /`

Serves the chat UI HTML.

### Response

```http
200 OK
content-type: text/html; charset=utf-8
```

## `GET /api/models`

Returns the model aliases available to the chat UI. The list is loaded from `[kirana].available_models` and `[kirana].model_identifiers` in `app/config.toml`.

### Response

```json
[
  {
    "name": "mistral",
    "identifier": "mistral/mistral-large-latest"
  },
  {
    "name": "gemini-3.1-flash",
    "identifier": "google-ai-studio/gemini-3.1-flash-lite-preview"
  }
]
```

## `GET /api/conversations`

Returns the sidebar conversation list ordered by most recently updated first. Soft-deleted conversations are excluded.

### Response

```json
[
  {
    "id": "1f15484d-d3a5-4571-8485-e0b43668a2f7",
    "title": "Weekly grocery totals",
    "created_at": "2026-05-11T02:36:26.783Z",
    "updated_at": "2026-05-11T02:55:57.602Z"
  }
]
```

## `POST /api/conversations`

Creates an empty conversation and returns its metadata. The `id` is a UUID and is also the LangGraph `thread_id`.

### Request

No request body.

### Response

```json
{
  "conversation": {
    "id": "813fa9f9-bbc1-4c20-b98b-31623f18ee4f",
    "title": "New conversation",
    "created_at": "2026-05-11T02:46:35.315Z",
    "updated_at": "2026-05-11T02:46:35.315Z"
  }
}
```

## `PATCH /api/conversations/{thread_id}`

Renames an active conversation. This updates the `conversations.title` field and refreshes `updated_at`.

### Path Parameters

| Name | Type | Description |
|---|---|---|
| `thread_id` | string | Conversation UUID and LangGraph thread ID. |

### Request

```json
{
  "title": "May grocery follow-ups"
}
```

### Response

```json
{
  "conversation": {
    "id": "1f15484d-d3a5-4571-8485-e0b43668a2f7",
    "title": "May grocery follow-ups",
    "created_at": "2026-05-11T02:36:26.783Z",
    "updated_at": "2026-05-11T02:55:57.602Z"
  }
}
```

### Errors

- `400 Bad Request`: title is empty after trimming whitespace.
- `404 Not Found`: conversation does not exist.

## `DELETE /api/conversations/{thread_id}`

Soft-deletes a conversation. This sets `conversations.is_active` to `0` and refreshes `updated_at`; the LangGraph checkpointed message history is left intact, but the conversation no longer appears in the sidebar or active conversation APIs.

### Path Parameters

| Name | Type | Description |
|---|---|---|
| `thread_id` | string | Conversation UUID and LangGraph thread ID. |

### Response

Returns `204 No Content` on success.

### Errors

- `404 Not Found`: conversation does not exist or is already deleted.

## `GET /api/conversations/{thread_id}/messages`

Returns the persisted LangGraph message history for an active conversation.

The persisted message history returns message roles and content. Per-request timing stats are returned in the final `end` event of the `/api/chat/stream` response because `total_tat_seconds` measures the full API request turnaround.

### Path Parameters

| Name | Type | Description |
|---|---|---|
| `thread_id` | string | Conversation UUID and LangGraph thread ID. |

### Response

```json
[
  {
    "role": "user",
    "content": "How much did I spend at Woolworths last month?"
  },
  {
    "role": "assistant",
    "content": "I can answer that once the retrieval tools are wired in."
  }
]
```

### Errors

- `404 Not Found`: conversation does not exist.

## `POST /api/chat/stream`

Sends a user message to the LangGraph chat graph and streams the assistant response from the Cloudflare AI Gateway as Server-Sent Events (SSE). The graph has an agent node and a dedicated tool-calling node with conditional routing. The registered `query_finance_db` tool runs validated read-only SQLite `SELECT` queries against the Cloudflare D1 finance database tables/views `receipts`, `receipt_items`, `splits`, `me_expenses`, `roommate1_expenses`, and `roommate2_expenses`; currency conversion should happen in SQL with expressions such as `ROUND(SUM(total_cents) / 100.0, 2)`. The model call is routed through Cloudflare AI Gateway using the selected model alias.

Gemini routes execute requested tools inside the agent node and then synthesize from plain-text tool results. This avoids replaying Gemini function-call parts through the OpenAI-compatible LangGraph tool loop, which can fail when Gemini requires `thought_signature` metadata.

Each model call is prefixed with `prompts/system_prompt.md` plus a runtime date line formatted as `Today's date is YYYY-MM-DD.`. The system message is injected at call time and is not persisted in the conversation transcript returned by `/api/conversations/{thread_id}/messages`.

If `thread_id` is omitted or unknown, the service creates a new conversation and derives the title from the first user message. No in-memory conversation state is used.

Finance database tool calls use a shared `D1Database` client created during application startup from `CLOUDFLARE_ACCOUNT_ID`, `CLOUDFLARE_API_TOKEN`, and `KIRANA_DB_ID`. If these are unavailable, the chat stream still starts, but the assistant receives a tool error and should report that structured finance lookup is unavailable. Tool calls and D1 queries are logged with Loguru and, when Logfire is enabled, recorded as spans with query text, row counts, and latency metadata.

LLM calls that fail with a 429 rate-limit response are retried with backoff waits of 15, 30, 45, and 60 seconds before each subsequent attempt (up to four waits; see `RATE_LIMIT_RETRY_DELAYS_SECONDS` in `app/chat/service.py`). Each wait emits a `rate_limit_retry` stream event and is logged to Logfire with the call name, model, retry attempt, delay, and error text.

`query_finance_db` rejects SQL that joins `receipts` or `receipt_items` with Splitwise tables or views (`splits`, `me_expenses`, `roommate1_expenses`, `roommate2_expenses`) in one statement. Query receipt totals and Splitwise shares separately, then reconcile in the answer (`app/tools/finance.py`).

### Request

```json
{
  "thread_id": "1f15484d-d3a5-4571-8485-e0b43668a2f7",
  "model": "mistral",
  "message": "Reply with exactly: pong",
  "system_prompt": null,
  "tools_enabled": true
}
```

| Field | Type | Required | Description |
|---|---|---:|---|
| `thread_id` | string or null | No | Existing conversation UUID. |
| `model` | string | Yes | Model alias from `GET /api/models`. |
| `message` | string | Yes | User message. Must be non-empty. |
| `system_prompt` | string or null | No | Per-request system prompt override for benchmark ablations. When omitted, the app reads `app/prompts/system_prompt.md`. The override is not persisted and does not modify files. |
| `tools_enabled` | boolean | No | Whether SQL and Vectorize tools are exposed to the selected model for this request. Defaults to `true`; benchmarks use `false` for the plain-LLM baseline. |

### Response

`200 OK` with `content-type: text/event-stream`. Each event is emitted as a single `data:` line containing a JSON object terminated by a blank line.

Event types:

- `start`: emitted once before any token deltas. Contains `thread_id` and the resolved `conversation` object (created on the fly if `thread_id` was omitted or unknown).
- `rate_limit_retry`: emitted when an LLM call receives a 429 rate-limit response and the service is waiting before retrying. Contains cumulative `retry_count`, per-call `retry_attempt`, `delay_seconds`, `max_retries`, and `call`.
- `delta`: emitted repeatedly as token chunks arrive from the model. Contains the incremental `content` string for the assistant message.
- `end`: emitted once after the model finishes. Contains `thread_id`, the refreshed `conversation`, and the full assistant `message` (including `stats` with `total_tat_seconds`, `input_tokens`, `output_tokens`, `total_tokens`, `tool_calls`, `tools`, and `rate_limit_retries`).
- `error`: emitted if the request fails (e.g. unknown model). Contains a `detail` string.

Example stream:

```
data: {"type":"start","thread_id":"1f15484d-d3a5-4571-8485-e0b43668a2f7","conversation":{"id":"1f15484d-d3a5-4571-8485-e0b43668a2f7","title":"Reply with exactly: pong","created_at":"2026-05-11T02:36:26.783Z","updated_at":"2026-05-11T02:36:26.783Z"}}

data: {"type":"delta","content":"po"}

data: {"type":"delta","content":"ng"}

data: {"type":"end","thread_id":"1f15484d-d3a5-4571-8485-e0b43668a2f7","conversation":{"id":"1f15484d-d3a5-4571-8485-e0b43668a2f7","title":"Reply with exactly: pong","created_at":"2026-05-11T02:36:26.783Z","updated_at":"2026-05-11T02:37:34.207Z"},"message":{"role":"assistant","content":"pong","stats":{"total_tat_seconds":1.347,"input_tokens":18,"output_tokens":3,"total_tokens":21,"tool_calls":0,"tools":[]}}}
```

### Errors

Errors during streaming are emitted as inline `error` events on the SSE stream rather than HTTP error status codes once the stream has started.

- `error` event with `detail` for unknown model alias or runtime failures.
- `422 Unprocessable Entity`: malformed request body or empty `message` (rejected before the stream starts).

## `POST /api/chat/image/stream`

Sends one agentic chat turn with an attached image and optional text question. The backend embeds the image with the same local embedding model and dimensions as ingestion (`[ingestion].embedding_model` / `[cloudflare].vectorize_index_dimension`), stores the vector in the per-process embedding cache under a short `embedding_key`, and injects that key into the user message. The agent must use the normal tool loop: call `search_item_vectors` with that `embedding_key` (do not call `embed_receipt_query` for the upload), compare Vectorize scores against `[kirana].receipt_image_match_threshold`, then call `query_finance_db` to confirm matching `receipt_items` joined to `receipts` before answering.

Uploaded images are resized before embedding to `[ingestion].embedding_image_max_dimension` on the longest side, currently `256`, without upscaling smaller images. If `[ingestion].embedding_device` is set, it is passed to `SentenceTransformer` as the local embedding device; an empty value uses the library default.

This endpoint streams the same SSE event shape as `POST /api/chat/stream`.

### Request

`multipart/form-data`

| Field | Type | Required | Description |
|---|---|---:|---|
| `thread_id` | string or empty | No | Existing conversation UUID. Empty creates a new conversation. |
| `model` | string | Yes | Model alias from `GET /api/models`. |
| `message` | string | No | Text question to ask alongside the image. If empty, the agent uses a default purchase-history image query. |
| `system_prompt` | string | No | Per-request system prompt override for benchmark ablations. When omitted, the app reads `app/prompts/system_prompt.md`. The override is not persisted and does not modify files. |
| `tools_enabled` | boolean | No | Whether SQL and Vectorize tools are exposed to the selected model for this request. Defaults to `true`. |
| `image` | file | Yes | Image to embed and make available to the agent. Must have an `image/*` content type and be 10 MB or smaller. |

### Errors

- `error` stream event with `detail`: upload is empty, too large, not an image, embedding fails, unknown model alias, or runtime tool/model failures.

## Observability

Chat requests are instrumented with Logfire when `KIRANA_DISABLE_LOGFIRE` is not set to `1`, `true`, or `yes`.

Each chat request emits:

- `chat_request` span with `thread_id`, model alias, model identifier, query text, and query length.
- Image-upload chat turns additionally emit embedding spans: `embedding.model_load` when the local model is first loaded, `embedding.image`, `embedding.image.decode`, `embedding.image.prepare`, and `embedding.image.encode`. These spans include image byte size, original and prepared dimensions, resize status, output dimensions, and elapsed timings for each stage.
- `chat query` event with the raw user query.
- OpenAI-compatible LLM span for the Cloudflare AI Gateway call.
- `llm_rate_limit_retry` spans when 429 rate-limit responses are retried.
- `chat response` event with raw response text, response length, total request turnaround time in seconds, input tokens, output tokens, total tokens, tool calls, tools, and rate-limit retry count.

The same query, response, total request turnaround time, and token metadata is written to the configured chat logfile, currently `[kirana].chat_log_file` in `app/config.toml`.
