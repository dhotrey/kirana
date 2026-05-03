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


class Config(pydantic.BaseModel):
    kirana: KiranaConfig
    cloudflare: CloudflareConfig
    log_level: str  # INFO, DEBUG, WARNING, ERROR, CRITICAL
    kb: KnowledgeBaseConfig
    tigris: TigrisConfig
