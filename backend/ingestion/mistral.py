from __future__ import annotations

import json
from typing import TYPE_CHECKING

from ingestion.llm_utils import usage_from_result
from ingestion.prompts import receipt_summary_prompt
from ingestion.schemas import Receipt
from ingestion.stats import TokenStats

if TYPE_CHECKING:
    from ingestion.context import IngestionContext


def summarise(receipt: Receipt, ctx: "IngestionContext") -> tuple[str, TokenStats]:
    prompt = "\n".join(
        [
            receipt_summary_prompt(ctx.prompts_dir),
            "",
            "Validated receipt JSON:",
            receipt.model_dump_json(indent=2),
        ]
    )
    result = ctx.mistral_agent.run_sync(prompt)
    usage = usage_from_result(result)
    output = getattr(result, "output", None)
    if output is None:
        output = getattr(result, "data", None)
    if output is None:
        output = result
    if isinstance(output, (dict, list)):
        summary = json.dumps(output)
    else:
        summary = str(output).strip()
    ctx.log.info(f"summary generated ({len(summary)} chars)")
    return summary, usage
