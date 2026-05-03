# Kirana — Ingestion Pipeline

## Overview

The ingestion pipeline is a local batch script that processes raw grocery receipt images into three persistent stores: a relational database (Cloudflare D1) for structured receipt data and Splitwise splits, a vector index (Cloudflare Vectorize) for semantic retrieval, and object storage (Cloudflare Tigris) for raw image archival. It runs on-demand from the local machine; there is no hosted orchestrator.

Splitwise data is a one-shot CSV import and does not go through the pipeline described below.

---

## Pipeline Steps

### 1. Read image from disk

The script reads a receipt image from a local directory. A pipeline run processes one image at a time; batch runs iterate over a directory sequentially.

### 2. Extract structured JSON via Gemini Flash (CF AI Gateway)

The image is sent to Gemini Flash via the Cloudflare AI Gateway. The model is prompted to extract a structured JSON document containing:

- `store_name` (string)
- `date` (ISO 8601 date string)
- `address` (string)
- `line_items` (array of `{ name, quantity, unit_price, inferred_category }`)
- `subtotal`, `gst`, `discounts`, `total` (all floats)

The CF AI Gateway handles network-level retries (5xx, timeouts). Application-level retry logic is separate — see step 3.

### 3. Validate JSON (Pydantic)

The extracted JSON is validated against a Pydantic model. Validation checks:

- All required fields are present
- `sum(line_items prices) ≈ total` within a fixed tolerance (e.g. ±5%)
- Date is parseable and not in the future

On validation failure, the error is injected back into the prompt and the request is re-sent to Gemini Flash. This retry loop lives in application code, not in CF AI Gateway. Maximum retry attempts and failure behaviour (skip receipt, write to error log) are fixed constants defined before eval runs.

Each attempt is logged as a Logfire span (`json_extraction`) with attempt number and error reason.

### 4. Generate semantic summary via cheap text model (e.g. Mistral)

The validated JSON is passed to a cheaper, higher-rate-limit text model. The model is prompted to generate a short natural language summary describing the semantic character of the shopping trip — food category skew (fresh vs. packaged), estimated scale, notable items — not a list restatement of line items.

This summary is the primary input to the embedding step and the main RAG retrieval surface. The VLM is not involved at this stage.

### 5. Insert row into Cloudflare D1

A row is inserted into the `receipts` table. D1's autoincrement provides the `receipt_id` (integer). All structured fields from the validated JSON are written at this step.

The `receipt_id` is the join key referenced by Cloudflare Vectorize metadata and the Tigris filename in subsequent steps.

### 6. Embed summary and upsert into Cloudflare Vectorize

The semantic summary text is embedded locally using Qwen3-VL-Embedding-2B. The resulting vector is upserted into Cloudflare Vectorize with the following metadata payload:

```json
{
  "receipt_id": 42,
  "store_name": "woolworths-metro",
  "date": "2026-03-15",
  "total": 87.40
}
```

The vector index is shared between receipt summaries and query-time pantry images, forming the cross-modal retrieval space described in the main README.

### 7. Upload image to Cloudflare Tigris

The raw receipt image is uploaded to Tigris under the filename:

```
<receipt_id>.<datetime>.<store_slug>.jpg
```

For example: `42.20260315T143200.woolworths-metro.jpg`

`store_slug` is the store name lowercased and hyphenated. `datetime` is ISO 8601 compact format. The Tigris URL is written back to the `receipts` row in D1 via an UPDATE.

This is the final step. If any earlier step failed, no image is written to Tigris and there are no orphaned objects to clean up.

---

## Splitwise Import (Separate Flow)

Splitwise data is exported manually as a CSV and imported directly into a D1 table (`splits`) as a one-shot operation. No VLM, embedding, or Tigris steps are involved.

The join between `splits` and `receipts` is fuzzy: matched on date proximity and total amount. Tolerance constants (e.g. ±2 days, ±5% amount) must be fixed before any query logic is written. Ambiguous matches (one Splitwise entry spanning multiple receipts) are flagged for LLM mediation at query time, not at ingestion time.

---

## Observability

All steps are instrumented as Pydantic Logfire spans. Each pipeline run produces:

- One canonical log line per receipt (success or failure reason)
- Per-step latency (Gemini call, Pydantic validation, summarisation, D1 insert, embedding, Vectorize upsert, Tigris upload)
- Token burn per model call (prompt + completion)
- Retry count and failure reason on JSON extraction failures

There are no persistent local telemetry processes. All traces go to Logfire.

---

## Error Handling Summary

| Step | Failure Mode | Behaviour |
|---|---|---|
| Gemini extraction | JSON unparseable or invalid | Retry with error in prompt (max N attempts), then skip and log |
| Pydantic validation | Field missing or sum mismatch | Same retry loop as above |
| D1 insert | DB error | Abort pipeline for this receipt, log, no downstream writes |
| Vectorize upsert | API error | Log and flag; receipt is in D1 but not retrievable via RAG |
| Tigris upload | API error | Log and flag; receipt is queryable but image not archived |

---

## Constants to Fix Before Eval

- Maximum JSON extraction retry attempts
- Splitwise fuzzy join tolerance (date window, amount tolerance)
- Pydantic sum-of-items tolerance
- Numerical answer tolerance for evaluation (±$3 or ±5%, whichever is larger)