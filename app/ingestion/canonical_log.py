from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from ingestion.schemas import Receipt
from ingestion.sources import ImageInput
from ingestion.stats import RetryCounts, TokenAccumulator, ValidationStats


class LatencySeconds(BaseModel):
    ocr: float = 0.0
    summary: float = 0.0
    db_insert: float = 0.0
    embedding: float = 0.0
    vectorize_upsert: float = 0.0
    tigris_upload: float = 0.0
    total: float = 0.0


class CanonicalLog(BaseModel):
    image_id: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    outcome: Literal["success", "failure"]
    error: str | None
    receipt_id: int | None
    store_name: str | None
    date: str | None
    retries: RetryCounts
    latency_seconds: LatencySeconds
    tokens: TokenAccumulator
    validation: ValidationStats
    dry_run: bool = False


def build_canonical_log(
    *,
    image: ImageInput,
    receipt: Receipt | None,
    receipt_id: int | None,
    outcome: Literal["success", "failure"],
    error: str | None,
    retries: RetryCounts,
    timings: dict[str, float],
    tokens: TokenAccumulator,
    dry_run: bool,
    sum_tolerance_pct: float,
) -> CanonicalLog:
    diff_pct = float(receipt.price_sum_diff_pct()) if receipt else 0.0
    validation = ValidationStats(
        subtotal_match=diff_pct <= sum_tolerance_pct if receipt else False,
        price_sum_diff_pct=diff_pct,
    )
    return CanonicalLog(
        image_id=image.image_id,
        outcome=outcome,
        error=error,
        receipt_id=receipt_id,
        store_name=receipt.store_name if receipt else None,
        date=receipt.date.isoformat() if receipt and receipt.date else None,
        retries=retries,
        latency_seconds=LatencySeconds(**timings),
        tokens=tokens,
        validation=validation,
        dry_run=dry_run,
    )


def write_canonical_log(log: CanonicalLog, logs_dir: Path) -> Path:
    logs_dir.mkdir(parents=True, exist_ok=True)
    key = str(log.receipt_id) if log.receipt_id and not log.dry_run else log.image_id
    path = logs_dir / f"{key}.json"
    path.write_text(log.model_dump_json(indent=2), encoding="utf-8")
    return path
