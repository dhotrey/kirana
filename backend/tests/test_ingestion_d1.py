from types import SimpleNamespace

import pytest
from pydantic import SecretStr

from ingestion.d1 import (
    RECEIPT_ITEM_INSERT_BATCH_SIZE,
    _extract_returning_id,
    build_items_insert_batches,
    build_receipt_insert,
    build_update_image_url,
    insert_receipt_with_items,
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


def test_extract_returning_id_from_cloudflare_d1_query_shape():
    # Cloudflare D1 SDK: SyncSinglePage[QueryResult] where page.result is a list of QueryResult
    # and QueryResult.results holds the returned rows.
    class FakeQueryResult:
        def __init__(self, results):
            self.results = results
            self.success = True
            self.meta = {}

    class FakeSinglePage:
        def __init__(self, result):
            self.result = result

    page = FakeSinglePage([FakeQueryResult([{"id": 123}])])
    assert _extract_returning_id(page) == 123


def test_insert_receipt_with_items_rolls_back_partial_insert_on_item_failure():
    class FakeLog:
        def debug(self, *_args):
            pass

        def info(self, *_args):
            pass

        def warning(self, *_args):
            pass

        def exception(self, *_args):
            pass

    class FakeDatabase:
        def __init__(self):
            self.calls = []
            self.item_insert_count = 0

        def query(self, *, database_id, account_id, sql, params):
            self.calls.append({"sql": sql, "params": params})
            if "RETURNING id" in sql:
                return SimpleNamespace(result=[SimpleNamespace(results=[{"id": 42}])])
            if sql.startswith("INSERT INTO receipt_items"):
                self.item_insert_count += 1
                if self.item_insert_count == 2:
                    raise RuntimeError("simulated D1 item batch failure")
            return SimpleNamespace(result=[])

    db = FakeDatabase()
    ctx = SimpleNamespace(
        cf_client=SimpleNamespace(d1=SimpleNamespace(database=db)),
        cloudflare_account_id=SecretStr("acct"),
        log=FakeLog(),
    )
    large_receipt = Receipt(
        store_name="Coles",
        item_count=RECEIPT_ITEM_INSERT_BATCH_SIZE + 1,
        subtotal="17.00",
        items=[
            ReceiptItem(item_name=f"Item {idx}", total_price="1.00")
            for idx in range(RECEIPT_ITEM_INSERT_BATCH_SIZE + 1)
        ],
    )

    with pytest.raises(RuntimeError, match="simulated D1 item batch failure"):
        insert_receipt_with_items(ctx, large_receipt)

    item_insert_sqls = [
        call["sql"] for call in db.calls if call["sql"].startswith("INSERT INTO receipt_items")
    ]
    assert len(item_insert_sqls) == 2
    assert db.calls[-2:] == [
        {"sql": "DELETE FROM receipt_items WHERE receipt_id = ?;", "params": [42]},
        {"sql": "DELETE FROM receipts WHERE id = ?;", "params": [42]},
    ]
