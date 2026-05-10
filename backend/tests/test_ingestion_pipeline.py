from types import SimpleNamespace

from loguru import logger

import ingestion.pipeline as pipeline
from ingestion.schemas import Receipt
from ingestion.sources import ImageInput
from ingestion.stats import TokenStats


class FakeContext:
    def __init__(self, logs_dir):
        self.cfg = SimpleNamespace(
            ingestion=SimpleNamespace(sum_tolerance_pct=5.0),
        )
        self.log = logger.bind(image_id="-")
        self.logs_dir = logs_dir
        self.effective_dry_run = False

    def with_log(self, log):
        self.log = log
        return self


def test_ingest_one_deletes_d1_receipt_after_partial_insert_failure(
    monkeypatch, tmp_path
):
    receipt = Receipt.model_validate(
        {
            "store_name": "Coles",
            "subtotal": "17.00",
            "items": [
                {"item_name": f"Item {idx}", "total_price": "1.00"}
                for idx in range(17)
            ],
        }
    )
    image = ImageInput(
        image_id="receipt-a",
        data=b"image",
        content_type="image/jpeg",
        extension=".jpg",
    )
    deleted_receipt_ids: list[int] = []

    monkeypatch.setattr(
        pipeline,
        "extract_receipt",
        lambda image, ctx: (receipt, 0, TokenStats()),
    )
    monkeypatch.setattr(
        pipeline, "summarise", lambda receipt, ctx: ("summary", TokenStats())
    )
    monkeypatch.setattr(pipeline, "insert_receipt", lambda ctx, receipt: 42)

    def fail_after_receipt_insert(ctx, receipt_id, items):
        raise RuntimeError("second D1 item batch failed")

    monkeypatch.setattr(pipeline, "insert_items", fail_after_receipt_insert)
    monkeypatch.setattr(
        pipeline,
        "delete_receipt",
        lambda ctx, receipt_id: deleted_receipt_ids.append(receipt_id),
    )

    result = pipeline.ingest_one(image, FakeContext(tmp_path))

    assert deleted_receipt_ids == [42]
    assert result.receipt_id is None
    assert result.canonical.outcome == "failure"
    assert result.canonical.receipt_id is None
    assert "second D1 item batch failed" in (result.canonical.error or "")
