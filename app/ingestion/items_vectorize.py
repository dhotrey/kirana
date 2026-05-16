from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from typing import Any

from ingestion.embeddings import Embedder
from utils.db.d1 import D1Database
from utils.types import Config

DISTINCT_ITEM_NAMES_SQL = """
SELECT DISTINCT item_name
FROM receipt_items
WHERE item_name IS NOT NULL
  AND TRIM(item_name) <> ''
ORDER BY item_name
"""


@dataclass(frozen=True)
class ItemVectorizeStats:
    total_items: int
    upserted_items: int
    skipped_items: int
    elapsed_seconds: float


def normalize_item_name(item_name: str) -> str:
    return " ".join(item_name.split())


def item_vector_id(item_name: str) -> str:
    normalized = normalize_item_name(item_name).casefold()
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    return f"item:{digest[:32]}"


def build_item_vector(item_name: str, values: list[float]) -> dict[str, Any]:
    normalized = normalize_item_name(item_name)
    return {
        "id": item_vector_id(normalized),
        "values": values,
        "metadata": {"item_name": normalized},
    }


def ensure_item_vector_index(
    *,
    cfg: Config,
    cf_client: Any,
    account_id: str,
    log: Any,
) -> None:
    index_name = cfg.cloudflare.vectorize_item_index_name
    try:
        cf_client.vectorize.indexes.get(index_name=index_name, account_id=account_id)
        log.info("item vector index exists index_name={}", index_name)
    except Exception as exc:
        if not _is_cloudflare_not_found(exc):
            raise
        log.info(
            "creating item vector index index_name={} dimensions={}",
            index_name,
            cfg.cloudflare.vectorize_index_dimension,
        )
        cf_client.vectorize.indexes.create(
            account_id=account_id,
            name=index_name,
            config={
                "dimensions": cfg.cloudflare.vectorize_index_dimension,
                "metric": "cosine",
            },
        )

    for field_name, field_type in zip(
        cfg.cloudflare.vectorize_item_index_metadata_fields,
        cfg.cloudflare.vectorize_item_index_metadata_field_types,
        strict=True,
    ):
        try:
            cf_client.vectorize.indexes.metadata_index.create(
                index_name=index_name,
                account_id=account_id,
                property_name=field_name,
                index_type=field_type,
            )
            log.info(
                "created item vector metadata index index_name={} field={} type={}",
                index_name,
                field_name,
                field_type,
            )
        except Exception as exc:
            if _is_cloudflare_already_exists(exc):
                log.info(
                    "item vector metadata index already exists index_name={} field={}",
                    index_name,
                    field_name,
                )
                continue
            raise


def fetch_distinct_item_names(db: D1Database) -> list[str]:
    rows = db.query_rows(DISTINCT_ITEM_NAMES_SQL).as_dicts()
    item_names: list[str] = []
    seen: set[str] = set()
    for row in rows:
        raw_item_name = row.get("item_name")
        if not isinstance(raw_item_name, str):
            continue
        item_name = normalize_item_name(raw_item_name)
        dedupe_key = item_name.casefold()
        if not item_name or dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        item_names.append(item_name)
    return item_names


def upsert_distinct_item_vectors(
    *,
    cfg: Config,
    db: D1Database,
    cf_client: Any,
    account_id: str,
    embedder: Embedder,
    log: Any,
    dry_run: bool = False,
) -> ItemVectorizeStats:
    started_at = time.perf_counter()
    item_names = fetch_distinct_item_names(db)
    upserted = 0
    skipped = 0
    upserted_ids: list[str] = []

    try:
        for index, item_name in enumerate(item_names, start=1):
            log.info(
                "embedding receipt item {}/{} item_name={!r}",
                index,
                len(item_names),
                item_name,
            )
            values = embedder.embed(item_name)
            if len(values) != cfg.cloudflare.vectorize_index_dimension:
                raise ValueError(
                    "Item vector dimension does not match Vectorize index dimension "
                    f"{cfg.cloudflare.vectorize_index_dimension}"
                )
            vector = build_item_vector(item_name, values)
            if dry_run:
                skipped += 1
                log.info("dry-run skipped item vector upsert id={}", vector["id"])
                continue

            cf_client.vectorize.indexes.upsert(
                index_name=cfg.cloudflare.vectorize_item_index_name,
                account_id=account_id,
                body={"vectors": [vector]},
            )
            upserted += 1
            upserted_ids.append(str(vector["id"]))
            log.info(
                "item vector upserted id={} item_name={!r} dim={}",
                vector["id"],
                item_name,
                len(values),
            )
    except Exception:
        if upserted_ids:
            log.warning(
                "item vector ingestion failed; deleting {} vectors from {}",
                len(upserted_ids),
                cfg.cloudflare.vectorize_item_index_name,
            )
            cf_client.vectorize.indexes.delete_by_ids(
                index_name=cfg.cloudflare.vectorize_item_index_name,
                account_id=account_id,
                ids=upserted_ids,
            )
        raise

    return ItemVectorizeStats(
        total_items=len(item_names),
        upserted_items=upserted,
        skipped_items=skipped,
        elapsed_seconds=round(time.perf_counter() - started_at, 3),
    )


def _is_cloudflare_not_found(exc: Exception) -> bool:
    status_code = getattr(exc, "status_code", None)
    if status_code == 404:
        return True
    return "index was not found" in str(exc).lower() or "not found" in str(exc).lower()


def _is_cloudflare_already_exists(exc: Exception) -> bool:
    text = str(exc).lower()
    status_code = getattr(exc, "status_code", None)
    return (
        status_code == 409 or "already exists" in text or "already been created" in text
    )
