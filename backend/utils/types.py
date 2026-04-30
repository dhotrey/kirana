import pydantic
from typing import Literal


class CloudflareConfig(pydantic.BaseModel):
    d1_database_name: str
    ai_gateway_name: str
    vectorize_index_name: str
    vectorize_embedding_model: str
    vectorize_index_dimension: int
    vectorize_index_metadata_fields: list[str]
    vectorize_index_metadata_field_types: list[Literal["string", "number", "boolean"]]


class InfraConfig(pydantic.BaseModel):
    cf_config: CloudflareConfig
    log_level: str  # INFO, DEBUG, WARNING, ERROR, CRITICAL
