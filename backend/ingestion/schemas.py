from __future__ import annotations

from datetime import date as Date, time as Time
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator


DEFAULT_SUM_TOLERANCE_PCT = Decimal("5.0")


def _decimal_from_context(
    info: ValidationInfo, key: str, default: Decimal
) -> Decimal:
    context = info.context if isinstance(info.context, dict) else {}
    value = context.get(key, default)
    return Decimal(str(value))


class ReceiptItem(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    item_name: str = Field(min_length=1)
    item_price: Decimal | None = Field(default=None, ge=0)
    quantity: float | None = Field(default=None, ge=0)
    unit_price: Decimal | None = Field(default=None, ge=0)
    total_price: Decimal = Field(ge=0)
    inferred_category: str | None = None


class Receipt(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    store_name: str = Field(min_length=1)
    date: Date | None = None
    time: Time | None = None
    address: str | None = None
    item_count: int | None = Field(default=None, ge=0)
    subtotal: Decimal | None = Field(default=None, ge=0)
    gst: Decimal | None = Field(default=None, ge=0)
    discounts: Decimal | None = Field(default=None, ge=0)
    items: list[ReceiptItem] = Field(default_factory=list)

    @field_validator("date")
    @classmethod
    def date_must_not_be_future(cls, value: Date | None) -> Date | None:
        if value is not None and value > Date.today():
            raise ValueError("receipt date cannot be in the future")
        return value

    @model_validator(mode="after")
    def items_sum_matches_subtotal(self, info: ValidationInfo) -> "Receipt":
        if self.subtotal is None or self.subtotal == 0:
            return self

        items_sum = self.items_total()
        tolerance = _decimal_from_context(
            info, "sum_tolerance_pct", DEFAULT_SUM_TOLERANCE_PCT
        )
        diff_pct = self.price_sum_diff_pct()
        if diff_pct > tolerance:
            raise ValueError(
                "items total "
                f"{items_sum} differs from subtotal {self.subtotal} by "
                f"{diff_pct:.2f}% (>{tolerance}%)"
            )
        return self

    def items_total(self) -> Decimal:
        return sum((item.total_price for item in self.items), Decimal("0"))

    def price_sum_diff_pct(self) -> Decimal:
        if self.subtotal is None or self.subtotal == 0:
            return Decimal("0")
        return abs(self.items_total() - self.subtotal) / self.subtotal * Decimal("100")

    def validation_stats(self) -> dict[str, Any]:
        diff_pct = float(self.price_sum_diff_pct())
        return {
            "subtotal_match": diff_pct <= float(DEFAULT_SUM_TOLERANCE_PCT),
            "price_sum_diff_pct": diff_pct,
        }
