from __future__ import annotations

import time
from contextlib import contextmanager, nullcontext
from typing import Iterator

from ingestion.canonical_log import build_canonical_log, write_canonical_log
from ingestion.d1 import insert_items, insert_receipt, update_image_url
from ingestion.gemini import extract_receipt
from ingestion.mistral import summarise
from ingestion.observability import Stopwatch, bind_image
from ingestion.result import IngestionResult
from ingestion.schemas import Receipt
from ingestion.sources import ImageInput
from ingestion.stats import RetryCounts, TokenAccumulator
from ingestion.tigris import upload_artifacts, write_dry_run_artifacts
from ingestion.vectorize import upsert_vector


@contextmanager
def _span(name: str, **attrs) -> Iterator[None]:
    try:
        import logfire

    except Exception:
        cm = nullcontext()
    else:
        cm = logfire.span(name, **attrs)
    with cm:
        yield


def ingest_one(image: ImageInput, ctx) -> IngestionResult:
    log = bind_image(image.image_id)
    ctx = ctx.with_log(log)
    timings: dict[str, float] = {}
    tokens = TokenAccumulator()
    retries = RetryCounts()
    receipt_id: int | None = None
    receipt: Receipt | None = None
    summary: str | None = None
    image_url: str | None = None
    error: str | None = None
    outcome = "failure"
    started = time.perf_counter()
    dry_run = ctx.effective_dry_run

    try:
        with _span("ingest", image_id=image.image_id):
            with Stopwatch("ocr", timings), _span("ingest.ocr", image_id=image.image_id):
                receipt, ocr_retries, gemini_tokens = extract_receipt(image, ctx)
                retries.ocr_validation_retries = ocr_retries
                retries.total_retries = ocr_retries
                tokens.add_gemini(gemini_tokens)

            with Stopwatch("summary", timings), _span(
                "ingest.summary", image_id=image.image_id
            ):
                summary, mistral_tokens = summarise(receipt, ctx)
                tokens.add_mistral(mistral_tokens)

            with Stopwatch("db_insert", timings), _span(
                "ingest.db_insert", image_id=image.image_id
            ):
                if dry_run:
                    receipt_id = 0
                    log.info("dry-run: skipping D1 insert")
                else:
                    receipt_id = insert_receipt(ctx, receipt)
                    insert_items(ctx, receipt_id, receipt.items)

            with Stopwatch("embedding", timings), _span(
                "ingest.embedding", image_id=image.image_id, receipt_id=receipt_id
            ):
                vector = ctx.embedder.embed(summary)
                log.debug(f"vector dim={len(vector)}")

            with Stopwatch("vectorize_upsert", timings), _span(
                "ingest.vectorize_upsert",
                image_id=image.image_id,
                receipt_id=receipt_id,
            ):
                if dry_run:
                    log.info(f"dry-run: skipping Vectorize upsert (vec dim={len(vector)})")
                else:
                    upsert_vector(ctx, receipt_id, vector, receipt)

            with Stopwatch("tigris_upload", timings), _span(
                "ingest.tigris_upload",
                image_id=image.image_id,
                receipt_id=receipt_id,
            ):
                if dry_run:
                    log.info("dry-run: skipping Tigris upload")
                    write_dry_run_artifacts(ctx.logs_dir, image, receipt, summary)
                else:
                    image_url = upload_artifacts(ctx, receipt_id, image, receipt, summary)
                    update_image_url(ctx, receipt_id, image_url)

        outcome = "success"
    except Exception as exc:
        log.exception("ingestion failed")
        error = f"{type(exc).__name__}: {exc}"
        outcome = "failure"
    finally:
        timings["total"] = round(time.perf_counter() - started, 4)
        canonical = build_canonical_log(
            image=image,
            receipt=receipt,
            receipt_id=receipt_id,
            outcome=outcome,
            error=error,
            retries=retries,
            timings=timings,
            tokens=tokens,
            dry_run=dry_run,
            sum_tolerance_pct=ctx.cfg.ingestion.sum_tolerance_pct,
        )
        path = write_canonical_log(canonical, ctx.logs_dir)
        log.info(
            "done "
            f"image_id={image.image_id} receipt_id={receipt_id} "
            f"elapsed={timings['total']:.2f}s outcome={outcome}"
        )
        log.debug(f"canonical log written to {path}")

    return IngestionResult(
        canonical=canonical,
        receipt=receipt,
        receipt_id=receipt_id,
        summary=summary,
        image_url=image_url,
    )
