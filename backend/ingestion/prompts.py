from __future__ import annotations

from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=32)
def load_prompt(prompts_dir: str | Path, name: str) -> str:
    prompt_path = Path(prompts_dir) / f"{name}.md"
    return prompt_path.read_text(encoding="utf-8")


def receipt_extraction_prompt(prompts_dir: str | Path) -> str:
    return load_prompt(prompts_dir, "receipt_extraction")


def receipt_summary_prompt(prompts_dir: str | Path) -> str:
    return load_prompt(prompts_dir, "receipt_summary")
