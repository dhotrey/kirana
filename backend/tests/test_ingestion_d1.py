from ingestion.d1 import (
    RECEIPT_ITEM_INSERT_BATCH_SIZE,
    build_items_insert_batches,
    build_receipt_insert,
    build_update_image_url,
    receipt_total_cents,
    to_cents,
)
from ingestion.schemas import Receipt, ReceiptItem
from ingest_kb import money_to_cents


def receipt() -> Receipt:
    return Receipt.model_validate(
        {
            "store_name": "Coles",
            "date": "2026-04-28",
            "time": "12:30:00",
            "address": "123 Test St",
            "item_count": 2,
            "subtotal": "10.00",
            "gst": "1.00",
            "discounts": "0.50",
            "items": [
                {"item_name": "Bread", "unit_price": "4.00", "total_price": "4.00"},
                {"item_name": "Milk", "unit_price": "6.00", "total_price": "6.00"},
            ],
        }
    )


def test_to_cents_matches_splitwise_money_to_cents():
    for value in ["25.00", "-9.45", "1.005"]:
        assert to_cents(value) == money_to_cents(value)


def test_total_cents_is_subtotal_minus_discount_plus_gst():
    assert receipt_total_cents(receipt()) == 1050
    assert receipt_total_cents(Receipt(store_name="A", items=[])) == 0


def test_build_receipt_insert_sql_and_params():
    sql, params = build_receipt_insert(receipt())
    assert "INSERT INTO receipts" in sql
    assert "RETURNING id;" in sql
    assert params == [
        "Coles",
        "2026-04-28",
        "12:30:00",
        "123 Test St",
        2,
        1000,
        100,
        50,
        1050,
    ]


def test_build_items_insert_batches_respects_d1_variable_limit():
    items = [ReceiptItem(item_name=f"Item {idx}", total_price="1.00") for idx in range(17)]
    batches = build_items_insert_batches(1, items)
    assert RECEIPT_ITEM_INSERT_BATCH_SIZE == 16
    assert len(batches) == 2
    assert len(batches[0][1]) == 16 * 6
    assert len(batches[1][1]) == 1 * 6


def test_build_update_image_url_sql():
    assert build_update_image_url("s3://x", 17) == (
        "UPDATE receipts SET image_url = ? WHERE id = ?;",
        ["s3://x", 17],
    )
