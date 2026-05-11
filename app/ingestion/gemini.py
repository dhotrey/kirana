from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING

from pydantic import ValidationError
from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.messages import BinaryImage, UserContent

from ingestion.llm_utils import extract_json_text, usage_from_result
from ingestion.prompts import receipt_extraction_prompt
from ingestion.rate_limit import retry_backoff_seconds
from ingestion.schemas import Receipt
from ingestion.sources import ImageInput
from ingestion.stats import TokenStats

if TYPE_CHECKING:
    from ingestion.context import IngestionContext


MAX_PREVIOUS_OUTPUT_CHARS = 12000


def _retry_output_context(json_text: str) -> str:
    if len(json_text) <= MAX_PREVIOUS_OUTPUT_CHARS:
        return json_text

    omitted = len(json_text) - MAX_PREVIOUS_OUTPUT_CHARS
    return (
        json_text[:MAX_PREVIOUS_OUTPUT_CHARS]
        + f"\n\n[Previous output truncated; omitted {omitted} characters.]"
    )


def _build_prompt(
    image: ImageInput,
    ctx: "IngestionContext",
    *,
    previous_json_text: str | None,
    previous_error: str | None,
) -> list[UserContent]:
    schema = json.dumps(Receipt.model_json_schema(), indent=2)
    prompt = receipt_extraction_prompt(ctx.prompts_dir)
    parts = [
        prompt,
        "",
        "Required JSON schema:",
        schema,
        "",
        f"Image id: {image.image_id}",
    ]
    if previous_json_text or previous_error:
        parts.extend(
            [
                "",
                "The previous attempt failed. Return a complete corrected JSON object "
                "that conforms to the schema. Preserve correctly extracted fields where "
                "possible, but fix the specific issue below.",
            ]
        )
    if previous_json_text:
        parts.extend(
            [
                "",
                "Previous output to repair:",
                _retry_output_context(previous_json_text),
            ]
        )
    if previous_error:
        parts.extend(["", f"Previous validation error: {previous_error}"])
    return [
        "\n".join(parts),
        BinaryImage(data=image.data, media_type=image.content_type),
    ]


def extract_receipt(
    image: ImageInput, ctx: "IngestionContext"
) -> tuple[Receipt, int, TokenStats]:
    log = ctx.log
    retries = 0
    token_totals = TokenStats()
    previous_json_text: str | None = None
    previous_error: str | None = None

    for attempt in range(1, ctx.cfg.ingestion.max_ocr_retries + 2):
        ctx.rate_limiter.wait(log)
        log.info(f"OCR attempt {attempt} for {image.image_id}")
        prompt = _build_prompt(
            image,
            ctx,
            previous_json_text=previous_json_text,
            previous_error=previous_error,
        )
        try:
            result = ctx.gemini_agent.run_sync(prompt)
        except ModelHTTPError as exc:
            raise RuntimeError(f"Gemini OCR request failed: {exc}") from exc
        usage = usage_from_result(result)
        token_totals.input_tokens += usage.input_tokens
        token_totals.output_tokens += usage.output_tokens

        json_text = extract_json_text(result)
        log.debug(f"raw Gemini JSON candidate: {json_text}")
        try:
            receipt = Receipt.model_validate_json(
                json_text,
                context={"sum_tolerance_pct": ctx.cfg.ingestion.sum_tolerance_pct},
            )
            log.info(f"OCR succeeded after {retries} retries")
            return receipt, retries, token_totals
        except (ValidationError, json.JSONDecodeError, ValueError) as exc:
            previous_json_text = json_text
            previous_error = str(exc)
            if attempt > ctx.cfg.ingestion.max_ocr_retries:
                log.debug(f"OCR validation failed terminally: {previous_error}")
                raise

            retries += 1
            log.debug(f"OCR validation retry {retries}: {previous_error}")
            backoff = retry_backoff_seconds(
                retries,
                strategy=ctx.cfg.ingestion.retry_backoff_strategy,
                base_seconds=ctx.cfg.ingestion.retry_backoff_base_seconds,
                max_seconds=ctx.cfg.ingestion.retry_backoff_max_seconds,
            )
            if backoff > 0:
                log.debug(f"OCR retry backoff sleep {backoff:.2f}s")
                time.sleep(backoff)

    raise RuntimeError("unreachable OCR retry loop state")
