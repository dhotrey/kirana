import pydantic
from typing import Literal


class KiranaConfig(pydantic.BaseModel):
    log_level: str  # INFO, DEBUG, WARNING, ERROR, CRITICAL


class CloudflareConfig(pydantic.BaseModel):
    d1_database_name: str
    ai_gateway_name: str
    vectorize_index_name: str
    vectorize_embedding_model: str
    vectorize_index_dimension: int
    vectorize_index_metadata_fields: list[str]
    vectorize_index_metadata_field_types: list[Literal["string", "number", "boolean"]]


class TigrisConfig(pydantic.BaseModel):
    bucket_name: str
    aws_endpoint_url_s3: str
    aws_endpoint_url_iam: str
    aws_region: str


class KnowledgeBaseConfig(pydantic.BaseModel):
    splitwise_csv_path: str


class IngestionConfig(pydantic.BaseModel):
    receipts_image_dir: str
    prompts_dir: str
    logs_dir: str
    gemini_model: str
    mistral_model: str
    gemini_rpm: int = pydantic.Field(ge=1)
    gemini_min_interval_seconds: float = pydantic.Field(gt=0)
    max_ocr_retries: int = pydantic.Field(ge=0)
    retry_backoff_strategy: Literal["constant", "linear", "exponential"]
    retry_backoff_base_seconds: float = pydantic.Field(ge=0)
    retry_backoff_max_seconds: float = pydantic.Field(ge=0)
    sum_tolerance_pct: float = pydantic.Field(ge=0)
    embedding_model: str
    embedding_dim: int = pydantic.Field(gt=0, le=1536)
    dry_run: bool

    @pydantic.model_validator(mode="after")
    def validate_retry_backoff(self) -> "IngestionConfig":
        if self.retry_backoff_max_seconds < self.retry_backoff_base_seconds:
            raise ValueError(
                "retry_backoff_max_seconds must be >= retry_backoff_base_seconds"
            )
        if 1536 % self.embedding_dim != 0:
            raise ValueError("embedding_dim must divide 1536 for Matryoshka truncation")
        return self


class Config(pydantic.BaseModel):
    kirana: KiranaConfig
    cloudflare: CloudflareConfig
    log_level: str  # INFO, DEBUG, WARNING, ERROR, CRITICAL
    kb: KnowledgeBaseConfig
    tigris: TigrisConfig
    ingestion: IngestionConfig
