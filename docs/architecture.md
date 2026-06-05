# Architecture

Kirana is a FastAPI chat UI backed by a LangGraph agent. The agent calls tools for finance lookup and semantic retrieval, routes model calls through Cloudflare AI Gateway, stores chat threads in local SQLite, reads finance data from Cloudflare D1, and searches receipt/item embeddings in Cloudflare Vectorize.

## Application Components

| Path | Role |
|---|---|
| `app/main.py` | FastAPI app, HTTP routes, lifespan wiring for D1 and `ChatService`. |
| `app/chat/service.py` | LangGraph graph, SSE streaming, conversation CRUD, image embedding, rate-limit retries, Logfire spans. |
| `app/chat/gateway.py` | Cloudflare AI Gateway OpenAI-compatible client; BYOK alias headers per provider. |
| `app/chat/schemas.py` | Pydantic models for API request/response payloads. |
| `app/tools/finance.py` | `query_finance_db` — validated read-only D1 `SELECT`. |
| `app/tools/vectorize.py` | `embed_receipt_query`, `search_receipt_vectors`, `search_item_vectors`; in-process embedding cache. |
| `app/ingestion/` | Receipt extraction, validation, summary, D1/Vectorize/Tigris writes, embeddings, observability. |
| `app/ingest_receipts.py` | Receipt image ingestion CLI. |
| `app/ingest_kb.py` | Splitwise CSV import CLI. |
| `app/load_item_vectors.py` | Distinct `receipt_items.item_name` → item Vectorize index CLI. |
| `app/setup.py` | Provisions D1 schema, Vectorize indexes, AI Gateway resource, Tigris bucket. |
| `app/bench.py` | Query-family benchmark runner against the local chat API. |
| `app/utils/config.py`, `app/utils/types.py` | Typed `config.toml` loading and validation. |
| `app/utils/db/d1.py` | Async Cloudflare D1 HTTP client used by finance tools and ingestion. |
| `app/utils/benchmarks/` | `BenchmarkClient` harness for streaming chat evaluation. |
| `app/prompts/` | `system_prompt.md` (default agent instructions), `system_icl.md` (benchmark ablation), ingestion prompts. |

Configuration keys for these components are documented in [configuration](./configuration.md).

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

## Implemented Tools

- `query_finance_db`: runs validated read-only SQLite `SELECT` queries against the Cloudflare D1 finance database. It only allows known finance tables/views and blocks write or schema-changing statements.
- `embed_receipt_query`: embeds a natural-language retrieval query with `Qwen/Qwen3-VL-Embedding-2B` and stores the vector in an in-memory per-process cache.
- `search_receipt_vectors`: searches the receipt-summary Vectorize index with optional metadata filters for `receipt_id`, `store_name`, and `date`.
- `search_item_vectors`: searches the item-name Vectorize index. This is the main retrieval path for uploaded image questions and fuzzy item matching.

### Uploaded-image chat turns

`ChatService` embeds the upload before the graph runs and places the resulting `embedding_key` in the `HumanMessage` text (`app/chat/service.py`). The model never receives raw pixels in chat. For those turns, retrieval is **`search_item_vectors` → `query_finance_db`**, not `embed_receipt_query` + `search_receipt_vectors` (receipt-summary search is for semantic trip themes from text, using keys produced by `embed_receipt_query`).

### In-process embedding cache

`embed_receipt_query`, uploaded-image turns, and `search_*_vectors` share a per-process dict on `ChatService` (`app/tools/vectorize.py` receives the cache at tool build time). Keys are short hashes; values are float vectors. The cache is not persisted and is lost on server restart — callers must re-embed or re-upload after a restart.

## Model Routing and Tool Execution

All chat and benchmark model calls go through Cloudflare AI Gateway (`app/chat/gateway.py`):

- Base URL: `https://gateway.ai.cloudflare.com/v1/{account_id}/{ai_gateway_name}/compat`
- Auth header: `cf-aig-authorization: Bearer {CLOUDFLARE_AI_GATEWAY_API_TOKEN}`
- BYOK alias: `cf-aig-byok-alias` is set to `gemini` for Google AI Studio models and `mistral` for Mistral models so the gateway attaches the correct provider key.

Tool execution diverges by model family inside the LangGraph `agent` node (`app/chat/service.py`):

| Model route | Detection | Tool loop | Why |
|---|---|---|---|
| Gemini / Google AI Studio | `model_routes_via_gemini()` in `chat/gateway.py` | In-agent loop: up to three tool rounds executed in `_gemini_agent_response`, then optional synthesis call | Replaying Gemini function-call parts through LangGraph `ToolNode` can fail when Gemini requires `thought_signature` metadata on replay. |
| Other models (e.g. Mistral) | default | LangGraph `ToolNode` with `tools_condition` routing | Standard OpenAI-compatible tool-calling loop. |

For Gemini with tools enabled, executed tool names are recorded on the final `AIMessage` as `additional_kwargs["kirana_tool_names"]` so SSE `end` stats match the non-Gemini path. Gemini chat requests also wait `gemini_min_interval_seconds` before the graph starts to reduce upstream 429s.

When `tools_enabled` is `false` (plain-LLM benchmark baseline), the agent node binds no tools and skips the Gemini in-agent loop.

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
