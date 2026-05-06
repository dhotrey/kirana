# Kirana Ingestion Pipeline

## Overview

Kirana ingestion is a set of local, explicitly-run flows that populate the grocery finance knowledge base. The receipt image flow and the Splitwise CSV import are part of the same ingestion boundary, but they are executed independently:

- Receipt images run through `backend/ingest_receipts.py`, which extracts, validates, summarizes, embeds, stores, archives, and logs each receipt.
- Splitwise exports are imported as a separate one-shot CSV flow into D1. They do not use VLM extraction, embedding, Vectorize, or Tigris.

The receipt flow writes to three persistent stores: Cloudflare D1 for structured receipt and item rows, Cloudflare Vectorize for semantic retrieval over receipt summaries, and Tigris for raw image and derived artifact archival. The pipeline runs on demand from the local machine; there is no hosted orchestrator or filesystem watcher.

---

## How to Run Receipt Ingestion

Run from `backend/`:

```sh
uv run python ingest_receipts.py
```

Process one specific image:

```sh
uv run python ingest_receipts.py --image ../knowledge-base/receipts/images/example.jpg
```

Exercise the full model and local artifact flow without writing to D1, Vectorize, or Tigris:

```sh
uv run python ingest_receipts.py --dry-run
```

Use a non-default config file:

```sh
uv run python ingest_receipts.py --config config.toml
```

`ingest_receipts.py` is intentionally thin. Most work happens in `backend/ingestion/`; the CLI owns startup, config loading, input selection, dry-run mode, and per-image orchestration.

---

## Receipt CLI Application Flow

```mermaid
flowchart TD
    A[Start ingest_receipts.py] --> B[Load .env and config.toml]
    B --> C[Build ingestion context]
    C --> D[Configure logging and Logfire]
    D --> E{--image provided?}
    E -->|Yes| F[Load that single image]
    E -->|No| G[Read supported images from receipts_image_dir]
    F --> H[Create image batch]
    G --> H
    H --> I[Process images sequentially]
    I --> J[Call ingestion pipeline for one image]
    J --> K{More images?}
    K -->|Yes| I
    K -->|No| L[Finish run]
```

At startup, the CLI loads configuration and credentials, creates API clients for Cloudflare and Tigris, initializes the embedding model, and prepares model agents routed through Cloudflare AI Gateway. It then resolves the input set:

- `--image` limits the run to a single file.
- Without `--image`, the configured `receipts_image_dir` is scanned for supported image files.
- Images are processed sequentially so rate limits, logs, and failures are easy to inspect.

---

## One Receipt Through the Pipeline

```mermaid
flowchart LR
    A[Receipt image] --> B[Gemini extraction]
    B --> C[Pydantic receipt validation]
    C --> D[Semantic summary]
    D --> E[D1 receipt and item rows]
    D --> F[Local embedding]
    F --> G[Vectorize summary vector]
    A --> H[Tigris raw image and artifacts]
    C --> H
    D --> H
    H --> I[D1 image URL update]
    B --> J[Logfire spans]
    C --> J
    D --> J
    E --> J
    G --> J
    H --> J
    J --> K[Canonical per-receipt log]
```

| Stage | What it does | Why it matters |
|---|---|---|
| Image loading | Reads receipt bytes and basic file metadata from disk. | Gives the pipeline a consistent image input regardless of single-image or batch mode. |
| Receipt extraction | Uses Gemini Flash through Cloudflare AI Gateway to convert the image into structured receipt data. | Turns visual receipts into machine-readable grocery facts. |
| Validation | Checks that the extracted receipt matches the expected Pydantic schema and accounting constraints. | Prevents malformed or obviously inconsistent data from entering the knowledge base. |
| Summary generation | Uses a cheaper text model to produce a short semantic description of the shopping trip. | Creates a retrieval surface for questions that are not simple exact SQL lookups. |
| D1 write | Stores receipt-level and item-level structured data. | Supports deterministic finance, date, total, store, and item queries. |
| Embedding and Vectorize upsert | Embeds the summary locally and stores it with receipt metadata. | Enables semantic and hybrid retrieval. |
| Tigris archival | Stores the raw image plus derived receipt and summary artifacts. | Keeps source evidence and derived artifacts available outside the database. |
| Canonical logging | Writes a compact success or failure record with timings, tokens, retries, and outcome. | Makes ingestion runs auditable and comparable during evaluation. |

---

## Receipt Extraction and Validation

The image is sent to Gemini Flash via Cloudflare AI Gateway. The model is prompted to extract a structured JSON document containing:

- `store_name`
- `date`
- `address`
- `items`, including item name, quantity, unit price, inferred category, and line total
- `subtotal`, `gst`, and `discounts`

The extracted JSON is validated against Pydantic models. Validation checks include:

- All required fields are present.
- Line-item totals are consistent with the receipt subtotal within the configured sum tolerance.
- The receipt date is parseable and not in the future.

On extraction or validation failure, the error is injected back into the prompt and the request is retried. Cloudflare AI Gateway handles network-level retries such as 5xx responses and timeouts; the schema and accounting retry loop lives in application code. Maximum retry attempts and failure behaviour must be fixed before evaluation runs.

Each extraction attempt is logged in Logfire with attempt number and error reason.

---

## Summary, Embedding, and Storage

After validation, the receipt JSON is passed to a cheaper text model, currently represented by the Mistral summary path. The prompt asks for a short natural-language summary of the shopping trip's semantic character: category skew, estimated scale, notable items, and other features useful for retrieval. It should not be a simple restatement of every line item.

The semantic summary is embedded locally using the configured Qwen embedding model and upserted into Cloudflare Vectorize with receipt metadata such as:

```json
{
  "receipt_id": 42,
  "store_name": "woolworths-metro",
  "date": "2026-03-15"
}
```

The vector index is shared between receipt summaries and query-time pantry images, forming the cross-modal retrieval space described in the main README.

Structured receipt and item rows are inserted into Cloudflare D1. D1's receipt ID is the join key referenced by Vectorize metadata and by the Tigris artifact path. The raw receipt image and derived artifacts are uploaded to Tigris under receipt-ID-prefixed keys such as `42/42-image.jpg`, `42/42-ocr.json`, and `42/42-summary.txt`, then the resulting image URL is written back to the corresponding D1 receipt row.

---

## Data Movement

```mermaid
flowchart TB
    subgraph Local["Local machine"]
        A[Receipt images]
        B[ingest_receipts.py]
        C[Prompts]
        D[Logs and dry-run artifacts]
    end

    subgraph Models["Model services via Cloudflare AI Gateway"]
        E[Gemini extraction model]
        F[Mistral summary model]
    end

    subgraph Stores["Persistent stores"]
        G[Cloudflare D1]
        H[Cloudflare Vectorize]
        I[Tigris object storage]
    end

    A --> B
    C --> B
    B --> E
    B --> F
    B --> G
    B --> H
    B --> I
    B --> D
```

The CLI coordinates local files, hosted model calls, and remote storage. Each execution is an explicit local batch run.

---

## Dry-Run Mode

Dry-run mode keeps the expensive and diagnostic parts of the flow while skipping persistent remote writes:

```mermaid
flowchart TD
    A[--dry-run] --> B[Extract receipt]
    B --> C[Validate receipt]
    C --> D[Generate summary]
    D --> E[Create embedding]
    E --> F[Skip D1 write]
    E --> G[Skip Vectorize upsert]
    E --> H[Skip Tigris upload]
    H --> I[Write local dry-run artifacts]
    I --> J[Write canonical log]
```

This is useful when checking prompt changes, validation behaviour, model access, or logging without mutating the shared knowledge base. Dry-run still records logs and local artifacts so the output can be inspected after the run.

---

## Splitwise Import

Splitwise data is exported manually as a CSV and imported directly into a D1 table, currently represented as `splits`. No VLM, embedding, Vectorize, or Tigris steps are involved.

The join between `splits` and `receipts` is fuzzy: matched on date proximity and total amount. Tolerance constants, such as date window and amount tolerance, must be fixed before query logic is evaluated. Ambiguous matches, including one Splitwise entry spanning multiple receipts, are flagged for LLM mediation at query time rather than resolved during ingestion.

This separation is intentional. Receipt ingestion produces evidence and retrieval surfaces; Splitwise import provides independent accounting records for reconciliation.

---

## Observability

All major receipt stages are instrumented as Pydantic Logfire spans. Each processed receipt produces:

- A Logfire trace with spans for extraction, validation, summary, D1 writes, embedding, Vectorize upsert, Tigris upload, and D1 image URL update.
- A canonical log entry with outcome, error message if any, retry counts, token counts, total elapsed time, dry-run status, and validation tolerance.
- In dry-run mode, local artifacts under the configured logs directory.

There are no persistent local telemetry services. Traces go to Logfire, and local artifacts/logs exist only as explicit run output.

---

## Error Handling

The CLI processes receipts independently. A failure on one image is captured in that image's canonical log and does not require the whole batch to be retried manually from scratch. The next image can continue through the same top-level loop.

| Step | Failure mode | Behaviour |
|---|---|---|
| Gemini extraction | JSON unparseable or invalid | Retry with error in prompt up to configured limit, then skip and log. |
| Pydantic validation | Field missing, date invalid, or accounting mismatch | Same retry loop as extraction. |
| D1 insert | Database error | Abort this receipt, log failure, and skip downstream persistent writes. |
| Vectorize upsert | API error | Log failure; the receipt may exist in D1 but not be retrievable via RAG. |
| Tigris upload | API error | Log failure; structured data may be queryable but the image may not be archived. |

---

## Constants to Fix Before Evaluation

- Maximum JSON extraction retry attempts.
- Pydantic sum-of-items tolerance.
- Splitwise fuzzy join tolerance, including date window and amount tolerance.
- Numerical answer tolerance for evaluation: `±$3` or `±5%`, whichever is larger.
