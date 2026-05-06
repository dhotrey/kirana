from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ingestion.schemas import Receipt

if TYPE_CHECKING:
    from ingestion.context import IngestionContext


def build_vector(
    receipt_id: int, values: list[float], receipt: Receipt
) -> dict[str, Any]:
    return {
        "id": str(receipt_id),
        "values": values,
        "metadata": {
            "receipt_id": receipt_id,
            "store_name": receipt.store_name,
            "date": receipt.date.isoformat() if receipt.date else "",
        },
    }


def upsert_vector(
    ctx: "IngestionContext", receipt_id: int, values: list[float], receipt: Receipt
) -> None:
    vector = build_vector(receipt_id, values, receipt)
    ctx.log.debug(f"vector dim={len(values)}")
    ctx.cf_client.vectorize.indexes.upsert(
        index_name=ctx.cfg.cloudflare.vectorize_index_name,
        account_id=ctx.cloudflare_account_id.get_secret_value(),
        body={"vectors": [vector]},
    )
    ctx.log.info(
        f"vector upserted (dim={len(values)}, metadata={vector['metadata']})"
    )
