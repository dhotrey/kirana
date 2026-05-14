from __future__ import annotations

import hashlib
import json
import os
import re
import time
from collections.abc import Mapping
from contextlib import nullcontext
from typing import Any, Literal

import logfire
from langchain_core.tools import BaseTool, tool
from loguru import logger
from pydantic import BaseModel, Field, model_validator

from ingestion.embeddings import Embedder
from utils.observability import logfire_enabled
from utils.types import Config

VECTOR_FILTER_OPERATORS = {"$eq", "$ne", "$in", "$nin", "$lt", "$lte", "$gt", "$gte"}
RANGE_FILTER_OPERATORS = {"$lt", "$lte", "$gt", "$gte"}
ISO_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class ReceiptQueryEmbeddingInput(BaseModel):
    query: str = Field(
        min_length=1,
        description=(
            "Natural-language receipt retrieval query to embed, such as "
            "'fresh vegetables shopping trips'."
        ),
    )


class ReceiptVectorSearchInput(BaseModel):
    embedding_key: str | None = Field(
        default=None,
        description=(
            "Embedding cache key returned by embed_receipt_query. Prefer this over "
            "passing a raw vector."
        ),
    )
    vector: list[float] | None = Field(
        default=None,
        description=(
            "Raw query vector. Use only if an embedding key is unavailable; it must "
            "match the configured Vectorize dimension."
        ),
    )
    filters: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Optional Cloudflare Vectorize metadata filter using only indexed fields: "
            "receipt_id, store_name, date. Date is indexed as YYYYMMDD number, "
            "but ISO YYYY-MM-DD inputs are accepted and normalized. Examples: "
            "{\"date\": {\"$gte\": 20260401, \"$lt\": 20260501}} or "
            "{\"store_name\": {\"$eq\": \"Coles\"}}."
        ),
    )
    top_k: int | None = Field(
        default=None,
        ge=1,
        le=100,
        description=(
            "Maximum nearest-neighbor matches to return. Defaults to "
            "kirana.receipt_vector_search_top_k."
        ),
    )

    @model_validator(mode="after")
    def validate_vector_source(self) -> "ReceiptVectorSearchInput":
        if not self.embedding_key and self.vector is None:
            raise ValueError("Provide embedding_key or vector")
        return self


class ItemVectorSearchInput(BaseModel):
    embedding_key: str | None = Field(
        default=None,
        description=(
            "Embedding cache key returned by embed_receipt_query or supplied in "
            "uploaded image context. Prefer this over passing a raw vector."
        ),
    )
    vector: list[float] | None = Field(
        default=None,
        description=(
            "Raw query vector. Use only if an embedding key is unavailable; it must "
            "match the configured Vectorize dimension."
        ),
    )
    top_k: int | None = Field(
        default=None,
        ge=1,
        le=100,
        description=(
            "Maximum nearest-neighbor item-name matches to return. Defaults to "
            "kirana.receipt_vector_search_top_k."
        ),
    )

    @model_validator(mode="after")
    def validate_vector_source(self) -> "ItemVectorSearchInput":
        if not self.embedding_key and self.vector is None:
            raise ValueError("Provide embedding_key or vector")
        return self


def _tool_span(tool_name: str, **attributes):
    if not logfire_enabled():
        return nullcontext()
    return logfire.span(f"tool.{tool_name}", tool_name=tool_name, **attributes)


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    return str(value)


def _match_to_dict(match: Any) -> dict[str, Any]:
    if hasattr(match, "model_dump"):
        raw = match.model_dump()
    elif isinstance(match, Mapping):
        raw = dict(match)
    else:
        raw = {
            "id": getattr(match, "id", None),
            "score": getattr(match, "score", None),
            "metadata": getattr(match, "metadata", None),
        }

    metadata = raw.get("metadata") if isinstance(raw, dict) else None
    if not isinstance(metadata, Mapping):
        metadata = {}
    receipt_id = metadata.get("receipt_id") or raw.get("id")
    try:
        receipt_id = int(receipt_id)
    except (TypeError, ValueError):
        pass

    return {
        "id": _jsonable(raw.get("id")),
        "receipt_id": _jsonable(receipt_id),
        "score": _jsonable(raw.get("score")),
        "metadata": _jsonable(dict(metadata)),
    }


def extract_vectorize_matches(result: Any) -> list[dict[str, Any]]:
    if result is None:
        return []
    if hasattr(result, "model_dump"):
        dumped = result.model_dump()
        matches = dumped.get("matches") if isinstance(dumped, dict) else None
    elif isinstance(result, Mapping):
        matches = result.get("matches")
    else:
        matches = getattr(result, "matches", None)
    if matches is None:
        return []
    return [_match_to_dict(match) for match in matches]


def _query_vector_from_input(
    *,
    embedding_key: str | None,
    vector: list[float] | None,
    embedding_cache: dict[str, list[float]],
    expected_dimensions: int,
) -> list[float]:
    query_vector = vector
    if query_vector is None and embedding_key:
        query_vector = embedding_cache.get(embedding_key)
    if query_vector is None:
        raise ValueError("Unknown embedding_key; create or supply an embedding first")
    if len(query_vector) != expected_dimensions:
        raise ValueError(
            "Query vector dimension does not match Vectorize index "
            f"dimension {expected_dimensions}"
        )
    return query_vector


def _validate_filter_value(
    *,
    field_name: str,
    field_type: Literal["string", "number", "boolean"],
    operator: str,
    value: Any,
) -> Any:
    if operator in RANGE_FILTER_OPERATORS and field_type == "boolean":
        raise ValueError(f"{field_name} does not support range filters")

    values = value if operator in {"$in", "$nin"} else [value]
    if operator in {"$in", "$nin"} and not isinstance(value, list):
        raise ValueError(f"{field_name} {operator} filter must be a list")

    normalized_values: list[Any] = []
    for item in values:
        normalized_item = _normalize_filter_value(field_name, field_type, item)
        if field_type == "string" and not isinstance(item, str):
            raise ValueError(f"{field_name} filter values must be strings")
        if field_type == "number" and (
            not isinstance(normalized_item, int | float) or isinstance(normalized_item, bool)
        ):
            raise ValueError(f"{field_name} filter values must be numbers")
        if field_type == "boolean" and not isinstance(item, bool):
            raise ValueError(f"{field_name} filter values must be booleans")
        normalized_values.append(normalized_item)

    if operator in {"$in", "$nin"}:
        return normalized_values
    return normalized_values[0]


def _normalize_filter_value(
    field_name: str,
    field_type: Literal["string", "number", "boolean"],
    value: Any,
) -> Any:
    if field_name == "date" and field_type == "number" and isinstance(value, str):
        if not ISO_DATE_PATTERN.match(value):
            raise ValueError(
                "date filters must use YYYYMMDD numbers or ISO YYYY-MM-DD strings"
            )
        return int(value.replace("-", ""))
    return value


def validate_vectorize_filter(
    filters: dict[str, Any] | None, cfg: Config
) -> dict[str, Any] | None:
    if not filters:
        return None
    field_types = dict(
        zip(
            cfg.cloudflare.vectorize_index_metadata_fields,
            cfg.cloudflare.vectorize_index_metadata_field_types,
            strict=True,
        )
    )
    for field_name, condition in filters.items():
        if field_name not in field_types:
            raise ValueError(
                "Vectorize filter can only use metadata fields: "
                + ", ".join(sorted(field_types))
            )
        field_type = field_types[field_name]
        if isinstance(condition, dict):
            if not condition:
                raise ValueError(f"{field_name} filter cannot be empty")
            unknown_ops = set(condition) - VECTOR_FILTER_OPERATORS
            if unknown_ops:
                raise ValueError(
                    f"{field_name} has unsupported operators: "
                    + ", ".join(sorted(unknown_ops))
                )
            normalized_condition: dict[str, Any] = {}
            for operator, value in condition.items():
                normalized_condition[operator] = _validate_filter_value(
                    field_name=field_name,
                    field_type=field_type,
                    operator=operator,
                    value=value,
                )
            filters[field_name] = normalized_condition
        else:
            filters[field_name] = _validate_filter_value(
                field_name=field_name,
                field_type=field_type,
                operator="$eq",
                value=condition,
            )

    compact = json.dumps(filters, separators=(",", ":"), sort_keys=True)
    if len(compact.encode("utf-8")) >= 2048:
        raise ValueError("Vectorize filter must be less than 2048 bytes")
    return filters


def build_vectorize_tools(
    cfg: Config, embedding_cache: dict[str, list[float]] | None = None
) -> list[BaseTool]:
    embedding_cache = embedding_cache if embedding_cache is not None else {}
    embedder: Embedder | None = None
    cf_client: Any | None = None

    def get_embedder() -> Embedder:
        nonlocal embedder
        if embedder is None:
            embedder = Embedder(
                cfg.ingestion.embedding_model,
                cfg.ingestion.embedding_dim,
                logger.bind(image_id="-", tool="embed_receipt_query"),
                image_max_dimension=cfg.ingestion.embedding_image_max_dimension,
                device=cfg.ingestion.embedding_device,
            )
        return embedder

    def get_cf_client() -> Any:
        nonlocal cf_client
        if cf_client is None:
            api_token = os.environ.get("CLOUDFLARE_API_TOKEN", "").strip()
            if not api_token:
                raise RuntimeError("CLOUDFLARE_API_TOKEN is not set")
            from cloudflare import Cloudflare

            cf_client = Cloudflare(api_token=api_token)
        return cf_client

    @tool(
        "embed_receipt_query",
        args_schema=ReceiptQueryEmbeddingInput,
        description=(
            "Embed a natural-language receipt retrieval query using the same local "
            "embedding model and dimensions used during receipt ingestion. Returns "
            "a short embedding_key for search_receipt_vectors."
        ),
    )
    def embed_receipt_query(query: str) -> str:
        started_at = time.perf_counter()
        normalized_query = " ".join(query.split())
        logger.info("tool call embed_receipt_query query={!r}", normalized_query)
        with _tool_span("embed_receipt_query", query=normalized_query) as span:
            try:
                vector = get_embedder().embed(normalized_query)
                key_material = (
                    f"{cfg.ingestion.embedding_model}:{cfg.ingestion.embedding_dim}:"
                    f"{normalized_query}"
                )
                embedding_key = hashlib.sha256(key_material.encode("utf-8")).hexdigest()[
                    :24
                ]
                embedding_cache[embedding_key] = vector
                response = {
                    "ok": True,
                    "embedding_key": embedding_key,
                    "dimensions": len(vector),
                    "model": cfg.ingestion.embedding_model,
                    "normalized": True,
                    "query": normalized_query,
                }
            except Exception as exc:
                logger.exception("tool call embed_receipt_query failed")
                response = {"ok": False, "error": str(exc)}

            elapsed_ms = round((time.perf_counter() - started_at) * 1000, 3)
            if span is not None and logfire_enabled():
                span.set_attributes(
                    {
                        "success": response["ok"],
                        "elapsed_ms": elapsed_ms,
                        "dimensions": response.get("dimensions", 0),
                        "error": response.get("error"),
                    }
                )
            return json.dumps(response)

    @tool(
        "search_receipt_vectors",
        args_schema=ReceiptVectorSearchInput,
        description=(
            "Search Cloudflare Vectorize receipt-summary embeddings. Use after "
            "embed_receipt_query. Supports metadata filters on indexed fields "
            "receipt_id (number), store_name (string), and date (ISO string). "
            "Date is indexed as a YYYYMMDD number. Use date range filters like "
            "{'date': {'$gte': 20260401, '$lt': 20260501}}. ISO YYYY-MM-DD "
            "date strings are also accepted and normalized before querying."
        ),
    )
    def search_receipt_vectors(
        embedding_key: str | None = None,
        vector: list[float] | None = None,
        filters: dict[str, Any] | None = None,
        top_k: int | None = None,
    ) -> str:
        started_at = time.perf_counter()
        effective_top_k = top_k or cfg.kirana.receipt_vector_search_top_k
        logger.info(
            "tool call search_receipt_vectors embedding_key={} top_k={} filters={!r}",
            embedding_key,
            effective_top_k,
            filters,
        )
        with _tool_span(
            "search_receipt_vectors",
            embedding_key=embedding_key,
            top_k=effective_top_k,
            filters=filters,
        ) as span:
            try:
                query_vector = _query_vector_from_input(
                    embedding_key=embedding_key,
                    vector=vector,
                    embedding_cache=embedding_cache,
                    expected_dimensions=cfg.cloudflare.vectorize_index_dimension,
                )
                validated_filters = validate_vectorize_filter(filters, cfg)
                query_kwargs: dict[str, Any] = {
                    "index_name": cfg.cloudflare.vectorize_index_name,
                    "account_id": os.environ.get("CLOUDFLARE_ACCOUNT_ID", "").strip(),
                    "vector": query_vector,
                    "top_k": effective_top_k,
                    "return_metadata": "indexed",
                    "return_values": False,
                }
                if not query_kwargs["account_id"]:
                    raise RuntimeError("CLOUDFLARE_ACCOUNT_ID is not set")
                if validated_filters is not None:
                    query_kwargs["filter"] = validated_filters
                result = get_cf_client().vectorize.indexes.query(**query_kwargs)
                matches = extract_vectorize_matches(result)
                response = {
                    "ok": True,
                    "index_name": cfg.cloudflare.vectorize_index_name,
                    "top_k": effective_top_k,
                    "filters": validated_filters,
                    "match_count": len(matches),
                    "receipt_ids": [
                        match["receipt_id"]
                        for match in matches
                        if isinstance(match.get("receipt_id"), int)
                    ],
                    "matches": matches,
                }
            except Exception as exc:
                logger.exception("tool call search_receipt_vectors failed")
                response = {"ok": False, "error": str(exc)}

            elapsed_ms = round((time.perf_counter() - started_at) * 1000, 3)
            if span is not None and logfire_enabled():
                span.set_attributes(
                    {
                        "success": response["ok"],
                        "elapsed_ms": elapsed_ms,
                        "match_count": response.get("match_count", 0),
                        "error": response.get("error"),
                    }
                )
            return json.dumps(response)

    @tool(
        "search_item_vectors",
        args_schema=ItemVectorSearchInput,
        description=(
            "Search Cloudflare Vectorize item-name embeddings built from distinct "
            "receipt_items.item_name values. Use this for uploaded image questions "
            "or fuzzy item identification before querying receipt_items in SQL. "
            "This item index only has item_name metadata; apply date, store, "
            "receipt_id, or amount constraints in query_finance_db after retrieving "
            "candidate item names."
        ),
    )
    def search_item_vectors(
        embedding_key: str | None = None,
        vector: list[float] | None = None,
        top_k: int | None = None,
    ) -> str:
        started_at = time.perf_counter()
        effective_top_k = top_k or cfg.kirana.receipt_vector_search_top_k
        logger.info(
            "tool call search_item_vectors embedding_key={} top_k={}",
            embedding_key,
            effective_top_k,
        )
        with _tool_span(
            "search_item_vectors",
            embedding_key=embedding_key,
            top_k=effective_top_k,
        ) as span:
            try:
                query_vector = _query_vector_from_input(
                    embedding_key=embedding_key,
                    vector=vector,
                    embedding_cache=embedding_cache,
                    expected_dimensions=cfg.cloudflare.vectorize_index_dimension,
                )
                account_id = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "").strip()
                if not account_id:
                    raise RuntimeError("CLOUDFLARE_ACCOUNT_ID is not set")
                result = get_cf_client().vectorize.indexes.query(
                    index_name=cfg.cloudflare.vectorize_item_index_name,
                    account_id=account_id,
                    vector=query_vector,
                    top_k=effective_top_k,
                    return_metadata="indexed",
                    return_values=False,
                )
                matches = extract_vectorize_matches(result)
                item_names = [
                    match["metadata"].get("item_name")
                    for match in matches
                    if isinstance(match.get("metadata"), dict)
                    and isinstance(match["metadata"].get("item_name"), str)
                ]
                response = {
                    "ok": True,
                    "index_name": cfg.cloudflare.vectorize_item_index_name,
                    "top_k": effective_top_k,
                    "match_count": len(matches),
                    "item_names": item_names,
                    "matches": matches,
                }
            except Exception as exc:
                logger.exception("tool call search_item_vectors failed")
                response = {"ok": False, "error": str(exc)}

            elapsed_ms = round((time.perf_counter() - started_at) * 1000, 3)
            if span is not None and logfire_enabled():
                span.set_attributes(
                    {
                        "success": response["ok"],
                        "elapsed_ms": elapsed_ms,
                        "match_count": response.get("match_count", 0),
                        "error": response.get("error"),
                    }
                )
            return json.dumps(response)

    return [embed_receipt_query, search_receipt_vectors, search_item_vectors]
