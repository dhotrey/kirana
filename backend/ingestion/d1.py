from __future__ import annotations

import os
from decimal import Decimal, ROUND_HALF_UP
from typing import TYPE_CHECKING, Any

from ingestion.schemas import Receipt, ReceiptItem

if TYPE_CHECKING:
    from ingestion.context import IngestionContext


D1_MAX_SQL_VARIABLES = 100
RECEIPT_ITEM_INSERT_COLUMNS = (
    "receipt_id",
    "item_name",
    "quantity",
    "unit_price_cents",
    "total_price_cents",
    "inferred_category",
)
RECEIPT_ITEM_INSERT_BATCH_SIZE = D1_MAX_SQL_VARIABLES // len(
    RECEIPT_ITEM_INSERT_COLUMNS
)


def to_cents(value: Decimal | str | int | float | None) -> int | None:
    if value is None:
        return None
    amount = Decimal(str(value))
    return int((amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def receipt_total_cents(receipt: Receipt) -> int:
    subtotal = receipt.subtotal or Decimal("0")
    discounts = receipt.discounts or Decimal("0")
    gst = receipt.gst or Decimal("0")
    return to_cents(subtotal - discounts + gst) or 0


def build_receipt_insert(receipt: Receipt) -> tuple[str, list[Any]]:
    sql = """
INSERT INTO receipts (
    store_name,
    date,
    time,
    address,
    item_count,
    subtotal_cents,
    gst_cents,
    discounts_cents,
    total_cents
)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
RETURNING id;
""".strip()
    params = [
        receipt.store_name,
        receipt.date.isoformat() if receipt.date else None,
        receipt.time.isoformat() if receipt.time else None,
        receipt.address,
        receipt.item_count,
        to_cents(receipt.subtotal),
        to_cents(receipt.gst),
        to_cents(receipt.discounts),
        receipt_total_cents(receipt),
    ]
    return sql, params


def _item_params(receipt_id: int, item: ReceiptItem) -> list[Any]:
    return [
        receipt_id,
        item.item_name,
        item.quantity,
        to_cents(item.unit_price),
        to_cents(item.total_price),
        item.inferred_category,
    ]


def build_items_insert_batches(
    receipt_id: int,
    items: list[ReceiptItem],
    batch_size: int = RECEIPT_ITEM_INSERT_BATCH_SIZE,
) -> list[tuple[str, list[Any]]]:
    if batch_size < 1:
        raise ValueError("batch_size must be at least 1")
    if not items:
        return []

    batches: list[tuple[str, list[Any]]] = []
    columns = ", ".join(RECEIPT_ITEM_INSERT_COLUMNS)
    row_placeholder = "(" + ", ".join(["?"] * len(RECEIPT_ITEM_INSERT_COLUMNS)) + ")"
    for idx in range(0, len(items), batch_size):
        batch = items[idx : idx + batch_size]
        placeholders = ", ".join([row_placeholder] * len(batch))
        sql = f"INSERT INTO receipt_items ({columns}) VALUES {placeholders};"
        params: list[Any] = []
        for item in batch:
            params.extend(_item_params(receipt_id, item))
        batches.append((sql, params))
    return batches


def build_update_image_url(image_url: str, receipt_id: int) -> tuple[str, list[Any]]:
    return "UPDATE receipts SET image_url = ? WHERE id = ?;", [image_url, receipt_id]


def _query(ctx: "IngestionContext", sql: str, params: list[Any] | None = None) -> Any:
    params = params or []
    ctx.log.debug(f"D1 SQL: {sql}")
    ctx.log.debug(f"D1 bind params count={len(params)}")
    return ctx.cf_client.d1.database.query(
        database_id=os.environ.get("KIRANA_DB_ID") or "",
        account_id=ctx.cloudflare_account_id.get_secret_value(),
        sql=sql,
        params=params,
    )


def _extract_returning_id(result: Any) -> int:
    """
    Cloudflare D1 SDK shapes vary depending on client + method.

    `d1.database.query(...)` returns a `SyncSinglePage[QueryResult]`, where:
    - page.result is a list of QueryResult
    - QueryResult.results is the list of returned rows (dict-like), e.g. [{"id": 123}]
    """

    def _unwrap(obj: Any) -> Any:
        if obj is None:
            return None
        # Common containers from SDK/HTTP clients
        for attr in ("result", "results", "rows"):
            if hasattr(obj, attr):
                val = getattr(obj, attr)
                if val is not None:
                    return val
        if isinstance(obj, dict):
            return obj.get("results") or obj.get("rows") or obj.get("result")
        return None

    rows = _unwrap(result)
    # SyncSinglePage[QueryResult] -> list[QueryResult]
    if isinstance(rows, list) and rows and hasattr(rows[0], "results"):
        rows = _unwrap(rows[0])
    # QueryResult -> list[dict]
    if hasattr(result, "results") and isinstance(rows, list) and rows and hasattr(rows[0], "results"):
        rows = _unwrap(rows[0])

    if isinstance(rows, list) and rows:
        first = rows[0]
        if isinstance(first, dict) and "id" in first:
            return int(first["id"])
        # Some clients may return pydantic/attrs objects for rows
        if hasattr(first, "id"):
            return int(getattr(first, "id"))

    raise ValueError(f"Could not extract receipt id from D1 result: {result!r}")


def insert_receipt(ctx: "IngestionContext", receipt: Receipt) -> int:
    sql, params = build_receipt_insert(receipt)
    ctx.log.debug(
        "computed receipt cents "
        f"subtotal={params[5]} gst={params[6]} discounts={params[7]} total={params[8]}"
    )
    result = _query(ctx, sql, params)
    receipt_id = _extract_returning_id(result)
    ctx.log.info(f"inserted receipt id={receipt_id} ({len(receipt.items)} items)")
    return receipt_id


def insert_items(ctx: "IngestionContext", receipt_id: int, items: list[ReceiptItem]) -> None:
    for sql, params in build_items_insert_batches(receipt_id, items):
        ctx.log.debug(f"computed item cents bind params={params}")
        _query(ctx, sql, params)


def delete_receipt(ctx: "IngestionContext", receipt_id: int) -> None:
    _query(ctx, "DELETE FROM receipt_items WHERE receipt_id = ?;", [receipt_id])
    _query(ctx, "DELETE FROM receipts WHERE id = ?;", [receipt_id])


def insert_receipt_with_items(ctx: "IngestionContext", receipt: Receipt) -> int:
    receipt_id = insert_receipt(ctx, receipt)
    try:
        insert_items(ctx, receipt_id, receipt.items)
    except Exception:
        ctx.log.warning(
            f"rolling back partial receipt insert id={receipt_id} after item failure"
        )
        try:
            delete_receipt(ctx, receipt_id)
        except Exception:
            ctx.log.exception(f"failed to roll back partial receipt insert id={receipt_id}")
        raise
    return receipt_id


def update_image_url(ctx: "IngestionContext", receipt_id: int, image_url: str) -> None:
    sql, params = build_update_image_url(image_url, receipt_id)
    _query(ctx, sql, params)
    ctx.log.info("image_url written back to D1")
