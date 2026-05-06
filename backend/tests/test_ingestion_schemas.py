from datetime import date, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from ingestion.schemas import Receipt


def valid_receipt(**overrides):
    data = {
        "store_name": "Woolworths",
        "date": "2026-04-28",
        "subtotal": "100.00",
        "items": [
            {"item_name": "Apples", "total_price": "40.00"},
            {"item_name": "Milk", "total_price": "60.00"},
        ],
    }
    data.update(overrides)
    return data


def test_receipt_happy_path_parses():
    receipt = Receipt.model_validate(valid_receipt())
    assert receipt.store_name == "Woolworths"
    assert receipt.items_total() == Decimal("100.00")


def test_receipt_requires_store_name():
    data = valid_receipt()
    del data["store_name"]
    with pytest.raises(ValidationError):
        Receipt.model_validate(data)


def test_items_sum_mismatch_over_tolerance_raises():
    with pytest.raises(ValidationError, match="differs from subtotal"):
        Receipt.model_validate(
            valid_receipt(items=[{"item_name": "Apples", "total_price": "94.98"}])
        )


def test_items_sum_boundary_uses_context_tolerance():
    Receipt.model_validate(
        valid_receipt(items=[{"item_name": "Apples", "total_price": "95.01"}]),
        context={"sum_tolerance_pct": 5.0},
    )
    with pytest.raises(ValidationError):
        Receipt.model_validate(
            valid_receipt(items=[{"item_name": "Apples", "total_price": "94.99"}]),
            context={"sum_tolerance_pct": 5.0},
        )


def test_missing_or_zero_subtotal_skips_sum_check():
    data = valid_receipt(items=[])
    del data["subtotal"]
    Receipt.model_validate(data)
    Receipt.model_validate(valid_receipt(subtotal="0", items=[]))


def test_future_date_raises():
    future = (date.today() + timedelta(days=1)).isoformat()
    with pytest.raises(ValidationError, match="future"):
        Receipt.model_validate(valid_receipt(date=future))


def test_negative_item_total_raises():
    with pytest.raises(ValidationError):
        Receipt.model_validate(
            valid_receipt(items=[{"item_name": "Apples", "total_price": "-1.00"}])
        )


def test_receipt_json_fixture_round_trips():
    raw = open("tests/fixtures/receipt.json", encoding="utf-8").read()
    receipt = Receipt.model_validate_json(raw)
    assert receipt.store_name == "Woolworths"
    assert receipt.price_sum_diff_pct() == Decimal("0")
