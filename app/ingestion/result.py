from __future__ import annotations

from pydantic import BaseModel

from ingestion.canonical_log import CanonicalLog
from ingestion.schemas import Receipt


class IngestionResult(BaseModel):
    canonical: CanonicalLog
    receipt: Receipt | None = None
    receipt_id: int | None = None
    summary: str | None = None
    image_url: str | None = None

    @property
    def ok(self) -> bool:
        return self.canonical.outcome == "success"

    def public_payload(self) -> dict:
        return {
            "ok": self.ok,
            "receipt_id": self.receipt_id,
            "summary": self.summary,
            "image_url": self.image_url,
            "store_name": self.canonical.store_name,
            "date": self.canonical.date,
            "validation": self.canonical.validation.model_dump(),
            "error": self.canonical.error,
        }
