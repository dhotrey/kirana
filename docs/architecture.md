# Architecture

Kirana is a FastAPI chat UI backed by a LangGraph agent. The agent calls tools for finance lookup and semantic retrieval, routes model calls through Cloudflare AI Gateway, stores chat threads in local SQLite, reads finance data from Cloudflare D1, and searches receipt/item embeddings in Cloudflare Vectorize.

## Component Map

| Component | Path | Role |
|---|---|---|
| FastAPI app | `app/main.py` | HTTP routes, lifespan wiring for D1 and `ChatService`. |
| Chat service | `app/chat/service.py` | LangGraph graph, SSE streaming, conversation SQLite, image embedding, Gemini tool loop. |
| AI Gateway client | `app/chat/gateway.py` | OpenAI-compatible chat model construction and BYOK alias headers. |
| Finance tools | `app/tools/finance.py` | Validated read-only D1 SQL (`query_finance_db`). |
| Vectorize tools | `app/tools/vectorize.py` | Embedding cache, receipt/item Vectorize search. |
| Ingestion pipeline | `app/ingestion/` | Receipt OCR, validation, summary, D1/Vectorize/Tigris writes. |
| Infrastructure setup | `app/setup.py` | D1, Vectorize, AI Gateway, Tigris provisioning. |
| D1 client | `app/utils/db/d1.py` | Cloudflare D1 query wrapper used by chat tools and ingestion. |
| Benchmark CLI | `app/bench.py` | Query-family evaluation against the streaming chat API. |

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

## Model Routing

All chat and ingestion model calls go through Cloudflare AI Gateway (`app/chat/gateway.py`). The gateway base URL is `https://gateway.ai.cloudflare.com/v1/{account_id}/{ai_gateway_name}/compat`, authenticated with `cf-aig-authorization`. Gemini and Mistral routes also send `cf-aig-byok-alias` (`gemini` or `mistral`) so the gateway selects the correct upstream provider key.

### Gemini vs. LangGraph tool execution

Non-Gemini models use the standard LangGraph loop: `agent` → `ToolNode` → `agent` until no tool calls remain.

Gemini models (`google-ai-studio/...` identifiers) bypass `ToolNode` and run an in-process tool loop in `ChatService._gemini_agent_response` (`app/chat/service.py`). This avoids replaying Gemini function-call parts through the OpenAI-compatible LangGraph tool loop, which can fail when Gemini requires `thought_signature` metadata.

Gemini tool execution limits:

- Up to **3** tool-request rounds per user turn.
- Tools are invoked directly with `ainvoke`; results are appended as `ToolMessage`s.
- After tool rounds (or when the model stops requesting tools), a synthesis prompt forces a final non-tool answer.
- `tools_enabled: false` skips tool binding entirely for benchmark plain-LLM baselines.
- Chat requests also wait `gemini_min_interval_seconds` (`app/config.toml`) before the first Gemini call via `GeminiRateLimiter`.

## Implemented Tools

- `query_finance_db`: runs validated read-only SQLite `SELECT` queries against the Cloudflare D1 finance database. It only allows known finance tables/views and blocks write or schema-changing statements. **Receipt and Splitwise tables cannot be combined in one query** — the validator rejects SQL that references both `receipts` and any Splitwise/accounting table (`splits`, `me_expenses`, `roommate1_expenses`, `roommate2_expenses`). Query each side separately and reconcile in the model response.
- `embed_receipt_query`: embeds a natural-language retrieval query with `Qwen/Qwen3-VL-Embedding-2B` and stores the vector in an in-memory per-process cache keyed by a 24-character SHA-256 prefix.
- `search_receipt_vectors`: searches the receipt-summary Vectorize index with optional metadata filters for `receipt_id`, `store_name`, and `date`.
- `search_item_vectors`: searches the item-name Vectorize index. This is the main retrieval path for uploaded image questions and fuzzy item matching.

### Tool I/O contract

All tools return JSON strings with an `ok` boolean. On success, finance and vector tools include result payloads; on failure they include `error`.

| Tool | Notable response fields | Limits and defaults |
|---|---|---|
| `query_finance_db` | `columns`, `row_count`, `rows`, `truncated` | Max **100** rows per call (`MAX_RESULT_ROWS` in `app/tools/finance.py`). Single `SELECT` only; no SQL comments. |
| `embed_receipt_query` | `embedding_key`, `dimensions`, `query` | Key is deterministic from model, dimension, and normalized query text. |
| `search_receipt_vectors` | `receipt_ids`, `matches`, `filters` | Default `top_k` from `[kirana].receipt_vector_search_top_k` (8). Filters validated against indexed metadata only; ISO `YYYY-MM-DD` dates normalized to `YYYYMMDD` numbers; filter JSON must be under 2048 bytes. |
| `search_item_vectors` | `item_names`, `matches` | Same default `top_k`. Only `item_name` metadata is indexed on this index. |

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
