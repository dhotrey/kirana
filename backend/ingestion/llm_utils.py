from __future__ import annotations

import json
import re
from typing import Any

from ingestion.stats import TokenStats


JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL | re.IGNORECASE)


def extract_json_text(value: Any) -> str:
    if isinstance(value, str):
        text = value.strip()
    elif hasattr(value, "output"):
        return extract_json_text(value.output)
    elif hasattr(value, "data"):
        return extract_json_text(value.data)
    else:
        text = json.dumps(value)

    fenced = JSON_FENCE_RE.search(text)
    if fenced:
        return fenced.group(1).strip()
    return text


def usage_from_result(result: Any) -> TokenStats:
    usage_obj = result.usage() if hasattr(result, "usage") else getattr(result, "usage", None)
    if usage_obj is None:
        return TokenStats()

    input_tokens = (
        getattr(usage_obj, "request_tokens", None)
        or getattr(usage_obj, "input_tokens", None)
        or getattr(usage_obj, "prompt_tokens", None)
        or 0
    )
    output_tokens = (
        getattr(usage_obj, "response_tokens", None)
        or getattr(usage_obj, "output_tokens", None)
        or getattr(usage_obj, "completion_tokens", None)
        or 0
    )
    return TokenStats(input_tokens=int(input_tokens), output_tokens=int(output_tokens))
