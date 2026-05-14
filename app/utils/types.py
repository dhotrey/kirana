import pydantic
from typing import Literal


class KiranaConfig(pydantic.BaseModel):
    log_level: str  # INFO, DEBUG, WARNING, ERROR, CRITICAL
    available_models: list[str] = pydantic.Field(default_factory=list)
    model_identifiers: dict[str, str] = pydantic.Field(default_factory=dict)
    chat_db_path: str = "db.sqlite"
    chat_log_file: str = "logs/chat.log"
    receipt_vector_search_top_k: int = pydantic.Field(default=8, ge=1, le=100)
    receipt_image_match_threshold: float = pydantic.Field(default=0.5, ge=0, le=1)

    @pydantic.model_validator(mode="after")
    def validate_model_aliases(self) -> "KiranaConfig":
        missing = [
            model for model in self.available_models if model not in self.model_identifiers
        ]
        if missing:
            raise ValueError(
                "available_models missing model_identifiers entries: "
                + ", ".join(missing)
            )
        return self


class CloudflareConfig(pydantic.BaseModel):
    d1_database_name: str
    ai_gateway_name: str
    vectorize_index_name: str
    vectorize_item_index_name: str
    vectorize_embedding_model: str
    vectorize_index_dimension: int
    vectorize_index_metadata_fields: list[str]
    vectorize_index_metadata_field_types: list[Literal["string", "number", "boolean"]]
    vectorize_item_index_metadata_fields: list[str] = pydantic.Field(
        default_factory=lambda: ["item_name"]
    )
    vectorize_item_index_metadata_field_types: list[
        Literal["string", "number", "boolean"]
    ] = pydantic.Field(default_factory=lambda: ["string"])


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
    embedding_image_max_dimension: int = pydantic.Field(default=256, gt=0)
    embedding_device: str | None = None
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
