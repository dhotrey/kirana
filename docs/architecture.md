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

## LangGraph Shape

The compiled graph in `app/chat/service.py` has two nodes:

- `agent`: builds the system prompt, selects the model, and either runs the standard OpenAI-compatible tool loop (Mistral and other non-Gemini aliases) or the Gemini-specific inline tool path described below.
- `tools`: LangGraph `ToolNode` over all registered tools.

Edges: `START → agent`, conditional `agent → tools | END` via `tools_condition`, and `tools → agent` for follow-up synthesis after tool results.

Conversation state is checkpointed in local SQLite through `AsyncSqliteSaver`. Tool routing and `tools_enabled` are passed through LangGraph `configurable` metadata per request rather than being hidden in synthesis prompts.

## Implemented Tools

- `query_finance_db`: runs validated read-only SQLite `SELECT` queries against the Cloudflare D1 finance database. It only allows known finance tables/views and blocks write or schema-changing statements.
- `embed_receipt_query`: embeds a natural-language retrieval query with `Qwen/Qwen3-VL-Embedding-2B` and stores the vector in an in-memory per-process cache.
- `search_receipt_vectors`: searches the receipt-summary Vectorize index with optional metadata filters for `receipt_id`, `store_name`, and `date`.
- `search_item_vectors`: searches the item-name Vectorize index. This is the main retrieval path for uploaded image questions and fuzzy item matching.

### Tool contracts and constraints

**`query_finance_db`** (`app/tools/finance.py`):

- Only single-statement `SELECT` queries; semicolons, SQL comments, and write/DDL keywords are rejected.
- Allowed tables/views: `receipts`, `receipt_items`, `splits`, `me_expenses`, `roommate1_expenses`, `roommate2_expenses`.
- Receipt totals and Splitwise/accounting views cannot appear in the same query; the agent must query them separately and reconcile in natural language.
- Results are capped at 100 rows (`truncated: true` when more rows exist). Amounts are stored as integer cents; dollar conversion belongs in SQL (`ROUND(cents / 100.0, 2)`).
- Responses are JSON: `{ok, sql, columns, row_count, rows, truncated}` or `{ok: false, error}`.

**Vectorize tools** (`app/tools/vectorize.py`):

- `embed_receipt_query` returns a 24-character hex `embedding_key` derived from model, dimension, and normalized query text. Keys live in a per-`ChatService` in-memory dict and are lost on process restart.
- `search_receipt_vectors` accepts `embedding_key` or a raw vector, optional metadata filters on indexed fields only, and `top_k` (default `[kirana].receipt_vector_search_top_k`). ISO `YYYY-MM-DD` date filters are normalized to numeric `YYYYMMDD`. Filter JSON must serialize to under 2048 bytes.
- `search_item_vectors` searches the item-name index only; date, store, receipt, and amount constraints must be applied afterward through `query_finance_db`.
- Vectorize query responses include `matches`, derived `receipt_ids` or `item_names`, and `match_count`.

**Embedding cache semantics**: text queries use `embed_receipt_query`; uploaded images are embedded in `ChatService` before the graph runs and expose their key in the `HumanMessage` text. Both paths share the same cache dict for the lifetime of the server process.

### Gemini vs. other model routes

Model aliases whose identifier contains `gemini` or `google-ai-studio` bypass the LangGraph `ToolNode` loop. Instead, `ChatService._gemini_agent_response`:

1. Calls the model with tools bound directly.
2. Executes requested tools inline and appends plain-text `ToolMessage` results (up to three tool rounds).
3. If tool rounds exhaust, sends a synthesis-only follow-up that forbids further tool calls.

This avoids replaying Gemini function-call parts through the OpenAI-compatible LangGraph tool loop, which can fail when Gemini requires `thought_signature` metadata. Non-Gemini aliases use the standard `agent ↔ tools` LangGraph loop with `model.bind_tools(...)`.

Gateway requests for all chat models go through `app/chat/gateway.py`, which sets `cf-aig-authorization` and a BYOK alias header (`gemini` or `mistral`) when applicable.

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
