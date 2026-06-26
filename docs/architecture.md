# Architecture

Kirana is a FastAPI chat UI backed by a LangGraph agent. The agent calls tools for finance lookup and semantic retrieval, routes model calls through Cloudflare AI Gateway, stores chat threads in local SQLite, reads finance data from Cloudflare D1, and searches receipt/item embeddings in Cloudflare Vectorize.

## Chat App

- `app/main.py` serves the FastAPI app and static chat UI from `app/index.html`.
- `app/chat/service.py` owns the LangGraph chat graph, conversation persistence, streaming SSE responses, image-upload handling, rate-limit retries, and Logfire spans.
- Chat history is stored locally in `db.sqlite` through LangGraph's SQLite checkpointer. Conversation metadata is stored in a local `conversations` table.
- Models are configured in `app/config.toml` and called through Cloudflare AI Gateway via `app/chat/gateway.py`.
- The active tools are registered in the graph from `app/tools/finance.py` and `app/tools/vectorize.py`.

```mermaid
flowchart TD
    User["User chat turn<br/>/api/chat/stream or /api/chat/image/stream"] --> Prep["ChatService.chat_stream<br/>validate model, ensure conversation,<br/>emit start event"]
    Prep --> ImageCheck{"Image uploaded?"}
    ImageCheck -- "No" --> Human["HumanMessage<br/>normalized text"]
    ImageCheck -- "Yes" --> ImageEmbed["Embed uploaded image<br/>Qwen3-VL-Embedding-2B<br/>cache embedding_key"]
    ImageEmbed --> ImagePrompt["HumanMessage with image context<br/>embedding_key + threshold + tool instructions"]
    Human --> Agent["LangGraph agent node<br/>system prompt + thread messages<br/>model via Cloudflare AI Gateway"]
    ImagePrompt --> Agent

    Agent --> ToolDecision{"tools_condition<br/>tool calls requested?"}
    ToolDecision -- "No" --> Final["Assistant response"]
    ToolDecision -- "Yes" --> ToolNode["LangGraph ToolNode"]

    ToolNode --> ReceiptEmbed["embed_receipt_query<br/>natural-language receipt recall query"]
    ToolNode --> ReceiptSearch["search_receipt_vectors<br/>receipt-summary Vectorize search<br/>optional receipt/store/date filters"]
    ToolNode --> FinanceTool["query_finance_db<br/>validated read-only SELECT"]
    ToolNode --> ItemSearch["search_item_vectors<br/>item-name Vectorize search"]

    ReceiptEmbed --> ReceiptCache[("In-memory embedding cache<br/>embedding_key")]
    ReceiptCache --> ToolNode
    ReceiptSearch --> ReceiptIndex[("Vectorize<br/>receipt summaries")]
    FinanceTool --> D1[("Cloudflare D1<br/>receipts, receipt_items,<br/>splits, expense views")]
    ItemSearch --> ItemIndex[("Vectorize<br/>receipt item names")]
    ReceiptIndex --> ToolNode
    D1 --> ToolNode
    ItemIndex --> ToolNode

    ReceiptSearch -. "returns candidate receipt_ids;<br/>agent grounds totals/items with SQL" .-> FinanceTool
    ItemSearch -. "returns candidate item_names;<br/>agent confirms purchases with SQL" .-> FinanceTool

    ToolNode --> Agent
    Final --> Stats["Serialize final SSE end event<br/>response + tokens + latency + tools"]
```

Non-Gemini models (for example `mistral`) follow the diagram above: the agent node binds tools, `tools_condition` routes to `ToolNode`, and tool results return to the agent. Gemini models bypass `ToolNode` and run tools inside `ChatService._gemini_agent_response` instead; see [Agent and tool execution](#agent-and-tool-execution).

## Agent and tool execution

`ChatService._build_graph` always compiles a LangGraph graph with `agent` and `tools` nodes, but the active execution path depends on the selected model alias and `tools_enabled`.

| Route | Detection | Tool execution |
|---|---|---|
| Non-Gemini | `model_routes_via_gemini` is false in `app/chat/gateway.py` | Standard LangGraph loop: agent binds tools, `tools_condition` routes to `ToolNode`, tool `ToolMessage` results return to the agent until the model stops requesting tools. |
| Gemini | Identifier contains `gemini` or `google-ai-studio` | In-agent loop in `ChatService._gemini_agent_response`: up to three tool-request rounds execute tools directly and append plain-text `ToolMessage` results, then a final synthesis call answers without binding tools. This avoids replaying Gemini function-call parts through the OpenAI-compatible LangGraph tool loop, which can fail when Gemini requires `thought_signature` metadata. |
| Tools disabled | `tools_enabled: false` on the chat request | Neither path exposes SQL or Vectorize tools. Used by the plain-LLM benchmark baseline. |

Additional runtime guards:

- Gemini chat turns call `GeminiRateLimiter.wait` before the graph starts, using `[ingestion].gemini_min_interval_seconds` from `app/config.toml`.
- LLM calls that receive HTTP 429 responses retry with `RATE_LIMIT_RETRY_DELAYS_SECONDS` (`15`, `30`, `45`, `60`) before failing.
- The runtime system prompt is `app/prompts/system_prompt.md` plus `Today's date is YYYY-MM-DD.`; per-request `system_prompt` overrides are injected at call time and are not persisted in thread history.

## Implemented Tools

- `query_finance_db`: runs validated read-only SQLite `SELECT` queries against the Cloudflare D1 finance database. It only allows known finance tables/views and blocks write or schema-changing statements.
- `embed_receipt_query`: embeds a natural-language retrieval query with `Qwen/Qwen3-VL-Embedding-2B` and stores the vector in an in-memory per-process cache.
- `search_receipt_vectors`: searches the receipt-summary Vectorize index with optional metadata filters for `receipt_id`, `store_name`, and `date`.
- `search_item_vectors`: searches the item-name Vectorize index. This is the main retrieval path for uploaded image questions and fuzzy item matching.

### `query_finance_db` validation rules

Validation lives in `app/tools/finance.py` (`validate_finance_sql`). The tool rejects queries that:

- are empty, contain SQL comments, or include more than one statement
- are not a single `SELECT`
- reference tables outside `receipts`, `receipt_items`, `splits`, `me_expenses`, `roommate1_expenses`, and `roommate2_expenses`
- combine `receipts` with Splitwise/accounting tables (`splits`, `me_expenses`, `roommate1_expenses`, `roommate2_expenses`) in one query. Receipt totals and Splitwise personal-share lookups must be queried separately, then reconciled in the model answer.

Successful responses return at most `100` rows (`truncated: true` when more rows matched). Amount columns are stored as integer cents; convert to dollars in SQL with expressions such as `ROUND(total_cents / 100.0, 2)`.

### Embedding cache

Text queries (`embed_receipt_query`) and uploaded images (`ChatService._message_with_uploaded_image_context`) store vectors in `ChatService._embedding_cache`, an in-process dict keyed by a short SHA-256 prefix. Cache entries:

- are scoped to the running `ChatService` process and are lost on server restart
- must be referenced by `embedding_key` in subsequent vector search tool calls during the same process lifetime
- use deterministic keys for identical text queries, but image keys are derived from image bytes

Default Vectorize `top_k` for both search tools comes from `[kirana].receipt_vector_search_top_k` in `app/config.toml` (currently `8`) unless a tool call overrides it.

### Uploaded-image chat turns

`ChatService` embeds the upload before the graph runs and places the resulting `embedding_key` in the `HumanMessage` text (`app/chat/service.py`). The model never receives raw pixels in chat. For those turns, retrieval is **`search_item_vectors` → `query_finance_db`**, not `embed_receipt_query` + `search_receipt_vectors` (receipt-summary search is for semantic trip themes from text, using keys produced by `embed_receipt_query`).

## Finance Store

Cloudflare D1 stores the structured finance data:

- `receipts`: one row per grocery receipt, including store, date, item count, subtotal, GST, discounts, total cents, and uploaded image URL.
- `receipt_items`: OCR-derived line items joined to `receipts.id`, including item name, quantity, unit price, total price, and inferred category.
- `splits`: imported Splitwise CSV rows with total cost and per-person amounts.
- `me_expenses`, `roommate1_expenses`, `roommate2_expenses`: views over `splits` that expose adjusted personal share columns.

## Knowledge Base and Modalities

### Receipt Images and OCR JSON

Receipt images are loaded from `knowledge-base/receipts/images` during ingestion. `app/ingest_receipts.py` runs the ingestion pipeline:

- Gemini extracts a structured receipt object from the image.
- Pydantic validates store, date, subtotal, GST, discounts, item totals, item names, quantities, and inferred categories.
- Mistral creates a natural-language receipt summary.
- D1 receives the receipt row and receipt item rows.
- The receipt summary is embedded with `Qwen/Qwen3-VL-Embedding-2B` and upserted into the receipt-summary Vectorize index.
- Tigris stores source artifacts and generated outputs for the ingested receipt.

### Splitwise Export

The Splitwise CSV path is configured in `app/config.toml` under `[knowledge_base].splitwise_csv_path`. `app/ingest_kb.py` imports the export into the `splits` table after converting money fields to integer cents. Splitwise data provides personal contribution and roommate share information that receipt OCR cannot infer.

### Query-Time Item Images

`POST /api/chat/image/stream` accepts an uploaded image and optional question. The backend resizes and embeds the image, stores the vector behind a short `embedding_key`, and injects that key into the chat turn. The agent then searches the item-name Vectorize index with `search_item_vectors` and confirms purchase evidence by querying `receipt_items` joined to `receipts`.

The assistant does not directly inspect the uploaded image pixels during the chat turn. It answers from item-vector matches and SQL-grounded receipt evidence.

### Vector Indexes

- `kirana-reciept-summaries`: receipt summary embeddings with indexed metadata for `receipt_id`, `store_name`, and `date`.
- `kirana-receipt-items`: distinct receipt item-name embeddings with indexed `item_name` metadata.
