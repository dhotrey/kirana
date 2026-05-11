from __future__ import annotations

from pydantic import BaseModel


class RetryCounts(BaseModel):
    ocr_validation_retries: int = 0
    total_retries: int = 0


class TokenStats(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0


class TokenAccumulator(BaseModel):
    gemini_input: int = 0
    gemini_output: int = 0
    mistral_input: int = 0
    mistral_output: int = 0

    def add_gemini(self, usage: TokenStats) -> None:
        self.gemini_input += usage.input_tokens
        self.gemini_output += usage.output_tokens

    def add_mistral(self, usage: TokenStats) -> None:
        self.mistral_input += usage.input_tokens
        self.mistral_output += usage.output_tokens


class ValidationStats(BaseModel):
    subtotal_match: bool = False
    price_sum_diff_pct: float = 0.0
