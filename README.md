# Kirana

Kirana is a local grocery finance QA prototype for answering questions over household receipts, receipt line items, Splitwise exports, and query-time item images.

The current app is a FastAPI chat UI backed by a LangGraph agent. The agent calls a small set of tools for finance lookup and semantic retrieval, routes model calls through Cloudflare AI Gateway, stores chat threads in local SQLite, reads finance data from Cloudflare D1, and searches receipt/item embeddings in Cloudflare Vectorize. Receipt ingestion converts grocery receipt images into validated JSON, stores receipt and item rows in D1, uploads raw artifacts to Tigris, creates receipt summaries, and embeds those summaries for semantic search.

Against a plain-LLM baseline (no tools, receipts injected as context), the ablation isolates how much of the performance delta is attributable to the harness itself versus model scale.

## Goals

- Answer household grocery spending questions using receipt totals from the structured finance database.
- Answer personal contribution questions using Splitwise-derived views, especially `me_expenses.my_share_cents`.
- Support semantic grocery-trip recall, such as finding "fresh veggies" trips, by searching embedded receipt summaries and then grounding answers in receipt rows and line items.
- Support uploaded item-image questions by embedding the uploaded image, searching a Vectorize index built from distinct receipt item names, and confirming candidate matches against receipt line items in D1.
- Support conversational follow-ups in a thread, including drilling from a monthly total into receipt lists, date grouping, store breakdowns, item counts, and personal contribution for a selected date.
- Capture useful trace data through Logfire and local logs, including chat requests, model calls, retries, tool calls, D1 query timing, Vectorize retrieval timing, image embedding stages, token counts, and end-to-end turnaround time.
- Expose inline response stats in the chat stream, including latency, token counts, tool count, tool names, and rate-limit retries.

## Non-Goals

- Cross-session memory persistence
- Live receipt scanning or real-time camera ingestion
- Multi-user support or budget advisory features
- Automatic Splitwise API sync (manual CSV export only)
- Persistent local telemetry processes (Prometheus, Grafana, local OTel collectors)
- A polished production UI

## Architecture

### Chat App

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

    ToolNode --> FinanceTool["query_finance_db<br/>validated read-only SELECT"]
    ToolNode --> ItemSearch["search_item_vectors<br/>item-name Vectorize search"]

    FinanceTool --> D1[("Cloudflare D1<br/>receipts, receipt_items,<br/>splits, expense views")]
    ItemSearch --> ItemIndex[("Vectorize<br/>receipt item names")]
    D1 --> ToolNode
    ItemIndex --> ToolNode

    ToolNode --> Agent
    Final --> Stats["Serialize final SSE end event<br/>response + tokens + latency + tools"]
```

### Implemented Tools

- `query_finance_db`: runs validated read-only SQLite `SELECT` queries against the Cloudflare D1 finance database. It only allows known finance tables/views and blocks write or schema-changing statements.
- `embed_receipt_query`: embeds a natural-language retrieval query with `Qwen/Qwen3-VL-Embedding-2B` and stores the vector in an in-memory per-process cache.
- `search_receipt_vectors`: searches the receipt-summary Vectorize index with optional metadata filters for `receipt_id`, `store_name`, and `date`.
- `search_item_vectors`: searches the item-name Vectorize index. This is the main retrieval path for uploaded image questions and fuzzy item matching.

### Finance Store

Cloudflare D1 stores the structured finance data:

- `receipts`: one row per grocery receipt, including store, date, item count, subtotal, GST, discounts, total cents, and uploaded image URL.
- `receipt_items`: OCR-derived line items joined to `receipts.id`, including item name, quantity, unit price, total price, and inferred category.
- `splits`: imported Splitwise CSV rows with total cost and per-person amounts.
- `me_expenses`, `roommate1_expenses`, `roommate2_expenses`: views over `splits` that expose adjusted personal share columns.

## Knowledge Base & Modalities

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

## Query Families

| Family | Query Shape | Implemented Capability |
|---|---|---|
| QF1: Household aggregation | Single-turn date-window totals. | Date-filtered receipt aggregation over `receipts.total_cents`. |
| QF2: Uploaded image purchase recall | Query-time item image matched against historical purchases. | Image embedding, item-vector search, and SQL confirmation against historical receipt line items. |
| QF3: Date and semantic trip analysis | Date-specific receipt totals, semantic trip discovery, and item inspection within identified trips. | Combination of D1 lookup, receipt-summary vector search, receipt ID narrowing, and line-item inspection. |
| QF4: Conversational drill-down | Multi-turn refinement from totals into receipts, grouped dates, stores, item counts, and personal share. | Threaded follow-up over prior context, structured receipt breakdowns, and Splitwise personal-share lookup. |

## Example Queries

### QF1

- How much did my household spend on groceries in the month of April?

### QF2

- Upload an item image and ask: have we ever bought this or something similar to this in our grocery trips before?

### QF3

- How much did I spend on 18th April? Can you list the receipts and the total amount spent?
- What were all the fresh veggies shopping trips in March?
- Can you tell me what I got at Woolworths in these identified trips?

### QF4

- How much did my household spend on groceries in the month of March?
- Can you list the different receipts involved in this as a list?
- Can you group them by date, list each date's total spend, and tell me which stores were involved on that day and how many items were in each store?
- Can you tell me what my contribution was for the groceries purchased on 18th March?

## Ablation Study

TODO: define the systems research question and ablation design once the evaluation harness and comparison conditions are settled.

## Metrics

### Quality

- **Task Success Rate**: binary success per test case. Numerical answers accept +/- 5% or +/- $3, whichever is larger.
- **Groundedness Score**: evaluates whether the answer cites or explains the right source basis, avoids hallucinated receipts/items, and distinguishes household totals from personal shares.
- **Retrieval Recall@k**: whether the correct receipt IDs or item names appear in top-k before SQL grounding.
- **Tool Call Accuracy**: whether the agent selected the right tools for the query family.

### Efficiency

- End-to-end latency and stage latency where instrumented, including image embedding, Vectorize search, D1 queries, and synthesis.
- Token burn, including prompt, completion, and total tokens when reported by the model provider.
- Tool call count per query.
- Retrieval precision: proportion of retrieved receipt IDs or item candidates that were relevant to the final grounded answer.

## Running Locally

Use Python 3.13+ and run commands from `app/`:

```sh
uv sync
uv run python main.py
```

Useful ingestion and indexing commands:

```sh
uv run python setup.py
uv run python ingest_kb.py
uv run python ingest_receipts.py
uv run python load_item_vectors.py
```

The app expects Cloudflare, Tigris, model gateway, and Logfire-related environment variables to be supplied through the local environment or `.env`. Raw receipts, exports, local databases, embeddings, and generated artifacts should stay out of git.
