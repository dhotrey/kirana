from __future__ import annotations

from types import SimpleNamespace
from datetime import date

import pytest

from ingestion.vectorize import vectorize_date_value
from tools.vectorize import extract_vectorize_matches, validate_vectorize_filter
from utils.types import (
    CloudflareConfig,
    Config,
    IngestionConfig,
    KiranaConfig,
    KnowledgeBaseConfig,
    TigrisConfig,
)


def _cfg() -> Config:
    return Config(
        kirana=KiranaConfig(
            log_level="DEBUG",
            available_models=["mistral"],
            model_identifiers={"mistral": "mistral/mistral-large-latest"},
        ),
        cloudflare=CloudflareConfig(
            d1_database_name="kirana",
            ai_gateway_name="kirana-ai-gateway",
            vectorize_index_name="kirana-reciept-summaries",
            vectorize_embedding_model="qwen3-vl-embedding-2b",
            vectorize_index_dimension=1536,
            vectorize_index_metadata_fields=["receipt_id", "store_name", "date"],
            vectorize_index_metadata_field_types=["number", "string", "number"],
        ),
        log_level="DEBUG",
        kb=KnowledgeBaseConfig(splitwise_csv_path="splitwise.csv"),
        tigris=TigrisConfig(
            bucket_name="bucket",
            aws_endpoint_url_s3="https://example.com",
            aws_endpoint_url_iam="https://example.com",
            aws_region="auto",
        ),
        ingestion=IngestionConfig(
            receipts_image_dir="receipts",
            prompts_dir="prompts",
            logs_dir="logs",
            gemini_model="gemini",
            mistral_model="mistral",
            gemini_rpm=5,
            gemini_min_interval_seconds=12.0,
            max_ocr_retries=3,
            retry_backoff_strategy="exponential",
            retry_backoff_base_seconds=1.0,
            retry_backoff_max_seconds=30.0,
            sum_tolerance_pct=5.0,
            embedding_model="Qwen/Qwen3-VL-Embedding-2B",
            embedding_dim=1536,
            dry_run=False,
        ),
    )


def test_validate_vectorize_filter_allows_date_range():
    filters = {"date": {"$gte": 20260401, "$lt": 20260501}}

    assert validate_vectorize_filter(filters, _cfg()) == filters


def test_validate_vectorize_filter_normalizes_iso_date_range():
    filters = {"date": {"$gte": "2026-04-01", "$lt": "2026-05-01"}}

    assert validate_vectorize_filter(filters, _cfg()) == {
        "date": {"$gte": 20260401, "$lt": 20260501}
    }


def test_validate_vectorize_filter_allows_receipt_id_in():
    filters = {"receipt_id": {"$in": [1, 2, 3]}}

    assert validate_vectorize_filter(filters, _cfg()) == filters


@pytest.mark.parametrize(
    "filters",
    [
        {"unknown": "value"},
        {"receipt_id": "not-a-number"},
        {"date": {"$contains": "2026-04"}},
        {"store_name": {"$in": "Coles"}},
    ],
)
def test_validate_vectorize_filter_rejects_invalid_filters(filters):
    with pytest.raises(ValueError):
        validate_vectorize_filter(filters, _cfg())


def test_extract_vectorize_matches_normalizes_cloudflare_match_shape():
    result = SimpleNamespace(
        matches=[
            SimpleNamespace(
                id="42",
                score=0.91,
                metadata={
                    "receipt_id": 42,
                    "store_name": "Coles",
                    "date": "2026-04-12",
                },
            )
        ]
    )

    assert extract_vectorize_matches(result) == [
        {
            "id": "42",
            "receipt_id": 42,
            "score": 0.91,
            "metadata": {
                "receipt_id": 42,
                "store_name": "Coles",
                "date": "2026-04-12",
            },
        }
    ]


def test_kirana_config_has_vector_search_top_k_default():
    assert KiranaConfig(log_level="DEBUG").receipt_vector_search_top_k == 8


def test_vectorize_date_value_uses_yyyymmdd_number():
    assert vectorize_date_value(date(2026, 4, 15)) == 20260415
    assert vectorize_date_value(None) is None
