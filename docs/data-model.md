# Data Model

This document describes the app-owned storage schema for Kirana. The source of truth for D1 table/view creation is `app/utils/db/db_setup.py`; Vectorize index names and metadata fields are configured in `app/config.toml`; local chat metadata is created in `app/chat/service.py`.

## Cloudflare D1

The finance database name is configured as `cloudflare.d1_database_name`, currently `kirana`.

### `splits`

Imported from the configured Splitwise CSV by `app/ingest_kb.py`.

| Column | Type | Required | Description |
|---|---|---:|---|
| `id` | `INTEGER PRIMARY KEY` | Yes | D1 row ID. |
| `date` | `TEXT` | Yes | Splitwise expense date. |
| `description` | `TEXT` | Yes | Splitwise expense description. |
| `category` | `TEXT` | No | Splitwise category. |
| `cost_cents` | `INTEGER` | Yes | Total expense amount in cents. |
| `currency` | `TEXT` | Yes | Currency code from the export. |
| `me_cents` | `INTEGER` | Yes | Splitwise exported amount for the primary user. |
| `roommate1_cents` | `INTEGER` | Yes | Splitwise exported amount for roommate 1. |
| `roommate2_cents` | `INTEGER` | Yes | Splitwise exported amount for roommate 2. |

### `receipts`

One row per ingested receipt image.

| Column | Type | Required | Description |
|---|---|---:|---|
| `id` | `INTEGER PRIMARY KEY` | Yes | Receipt ID used as the join key for `receipt_items`, Vectorize metadata, and Tigris artifact paths. |
| `store_name` | `TEXT` | Yes | Extracted store name. |
| `date` | `TEXT` | No | Extracted receipt date. |
| `time` | `TEXT` | No | Extracted receipt time when available. |
| `address` | `TEXT` | No | Extracted store address. |
| `item_count` | `INTEGER` | No | Number of extracted receipt line items. |
| `subtotal_cents` | `INTEGER` | No | Receipt subtotal in cents. |
| `gst_cents` | `INTEGER` | No | GST in cents. |
| `discounts_cents` | `INTEGER` | No | Discounts in cents. |
| `total_cents` | `INTEGER` | Yes | Receipt total in cents. |
| `image_url` | `TEXT` | No | Tigris object URL for the uploaded source image. |
| `created_at` | `TEXT` | Yes | D1 insertion timestamp, defaults to `CURRENT_TIMESTAMP`. |

### `receipt_items`

Line items extracted from each receipt.

| Column | Type | Required | Description |
|---|---|---:|---|
| `id` | `INTEGER PRIMARY KEY` | Yes | Line item row ID. |
| `receipt_id` | `INTEGER` | Yes | Foreign key to `receipts.id`; deleted with the parent receipt. |
| `item_name` | `TEXT` | Yes | Extracted item name. |
| `quantity` | `REAL` | No | Extracted quantity. |
| `unit_price_cents` | `INTEGER` | No | Unit price in cents when available. |
| `total_price_cents` | `INTEGER` | Yes | Line total in cents. |
| `inferred_category` | `TEXT` | No | Model-inferred grocery category. |

Foreign key:

```sql
FOREIGN KEY (receipt_id)
    REFERENCES receipts(id)
    ON DELETE CASCADE
```

## D1 Views

The setup script creates one adjusted-share view per household member over `splits`.

### `me_expenses`

Adds:

```sql
CASE
    WHEN me_cents > 0 THEN cost_cents - me_cents
    ELSE -me_cents
END AS my_share_cents
```

Query-time access through `query_finance_db` must not join `receipts` or `receipt_items` with these Splitwise views in a single SQL statement. Query receipt evidence and personal-share accounting separately, then reconcile in the agent answer.

### `roommate1_expenses`

Adds:

```sql
CASE
    WHEN roommate1_cents > 0 THEN cost_cents - roommate1_cents
    ELSE -roommate1_cents
END AS roommate1_share_cents
```

### `roommate2_expenses`

Adds:

```sql
CASE
    WHEN roommate2_cents > 0 THEN cost_cents - roommate2_cents
    ELSE -roommate2_cents
END AS roommate2_share_cents
```

## D1 Indexes

| Index | Table | Columns | Purpose |
|---|---|---|---|
| `idx_receipts_date` | `receipts` | `date` | Date-window receipt aggregation and lookup. |
| `idx_receipt_items_receipt_id` | `receipt_items` | `receipt_id` | Receipt-to-line-item joins. |
| `idx_receipt_items_name` | `receipt_items` | `item_name` | Item-name lookup and fuzzy candidate verification. |

## Cloudflare Vectorize

Both Vectorize indexes use:

- dimensions: `1536`
- distance metric: `cosine`
- embedding model: `Qwen/Qwen3-VL-Embedding-2B` locally, with `cloudflare.vectorize_embedding_model` configured as `qwen3-vl-embedding-2b`

### `kirana-reciept-summaries`

Receipt summary embeddings written by `app/ingest_receipts.py`.

| Metadata Field | Type | Description |
|---|---|---|
| `receipt_id` | `number` | Join key back to `receipts.id` and Tigris artifact naming. |
| `store_name` | `string` | Store filter metadata. |
| `date` | `number` | Numeric `YYYYMMDD` receipt date for Vectorize range filters. |

Use this index for semantic trip retrieval, then ground final answers with D1 queries.

### `kirana-receipt-items`

Distinct receipt item-name embeddings written by `app/load_item_vectors.py`.

| Metadata Field | Type | Description |
|---|---|---|
| `item_name` | `string` | Normalized receipt line-item name. |

Vector IDs are deterministic SHA-256 based IDs over normalized, case-folded item names:

```text
item:<first-32-hex-chars>
```

Use this index for uploaded item-image questions and fuzzy item matching, then confirm matches against `receipt_items` joined to `receipts`.

## Local SQLite

The local chat database path is configured as `kirana.chat_db_path`, currently `db.sqlite`.

### `conversations`

Created by `app/chat/service.py`.

| Column | Type | Required | Description |
|---|---|---:|---|
| `id` | `TEXT PRIMARY KEY` | Yes | Conversation UUID and LangGraph `thread_id`. |
| `title` | `TEXT` | Yes | Sidebar title. |
| `is_active` | `INTEGER` | Yes | Soft-delete flag; active conversations use `1`. |
| `created_at` | `TEXT` | Yes | UTC creation timestamp. |
| `updated_at` | `TEXT` | Yes | UTC update timestamp. |

LangGraph checkpoint tables are also stored in this SQLite database through `langgraph-checkpoint-sqlite`. They are managed by the library's `AsyncSqliteSaver.setup()` and should not be treated as app-owned schema.
