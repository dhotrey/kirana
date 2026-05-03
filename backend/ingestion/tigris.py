from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from ingestion.schemas import Receipt
from ingestion.sources import ImageInput

if TYPE_CHECKING:
    from ingestion.context import IngestionContext


def artifact_keys(receipt_id: int, image: ImageInput) -> tuple[str, str, str]:
    prefix = str(receipt_id)
    return (
        f"{prefix}/{receipt_id}-image{image.extension}",
        f"{prefix}/{receipt_id}-ocr.json",
        f"{prefix}/{receipt_id}-summary.txt",
    )


def image_url_for(ctx: "IngestionContext", key: str) -> str:
    endpoint = ctx.cfg.tigris.aws_endpoint_url_s3.rstrip("/")
    return f"{endpoint}/{ctx.cfg.tigris.bucket_name}/{key}"


def upload_artifacts(
    ctx: "IngestionContext",
    receipt_id: int,
    image: ImageInput,
    receipt: Receipt,
    summary: str,
) -> str:
    image_key, ocr_key, summary_key = artifact_keys(receipt_id, image)
    ctx.log.debug(f"Tigris PUT image key={image_key}")
    ctx.s3_client.put_object(
        Bucket=ctx.cfg.tigris.bucket_name,
        Key=image_key,
        Body=image.data,
        ContentType=image.content_type,
    )
    ctx.log.debug(f"Tigris PUT OCR key={ocr_key}")
    ctx.s3_client.put_object(
        Bucket=ctx.cfg.tigris.bucket_name,
        Key=ocr_key,
        Body=receipt.model_dump_json(indent=2).encode("utf-8"),
        ContentType="application/json",
    )
    ctx.log.debug(f"Tigris PUT summary key={summary_key}")
    ctx.s3_client.put_object(
        Bucket=ctx.cfg.tigris.bucket_name,
        Key=summary_key,
        Body=summary.encode("utf-8"),
        ContentType="text/plain",
    )
    image_url = image_url_for(ctx, image_key)
    ctx.log.info(f"tigris artifacts uploaded ({image_url})")
    return image_url


def write_dry_run_artifacts(
    logs_dir: Path, image: ImageInput, receipt: Receipt, summary: str
) -> None:
    target_dir = logs_dir / "dry-run" / image.image_id
    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / f"{image.image_id}-image{image.extension}").write_bytes(image.data)
    (target_dir / f"{image.image_id}-ocr.json").write_text(
        receipt.model_dump_json(indent=2), encoding="utf-8"
    )
    (target_dir / f"{image.image_id}-summary.txt").write_text(
        summary, encoding="utf-8"
    )
