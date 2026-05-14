from __future__ import annotations

import argparse
import os

import dotenv
from cloudflare import Cloudflare
from loguru import logger

from ingestion.embeddings import Embedder
from ingestion.items_vectorize import (
    ensure_item_vector_index,
    upsert_distinct_item_vectors,
)
from ingestion.observability import configure_logfire, configure_logging
from utils.config import load_config
from utils.db.d1 import D1Database

dotenv.load_dotenv()

os.environ["TRANSFORMERS_VERBOSITY"] = "error"
os.environ["TRANSFORMERS_NO_ADVISORY_WARNINGS"] = "1"
os.environ["HF_HUB_OFFLINE"] = "1"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Load distinct receipt item-name vectors into Cloudflare Vectorize"
    )
    parser.add_argument(
        "--config",
        default="config.toml",
        help="Path to app/ config.toml",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Read D1 and embed items, but skip Vectorize writes.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    cfg = load_config(args.config)
    configure_logging(cfg)
    configure_logfire()

    account_id = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "").strip()
    api_token = os.environ.get("CLOUDFLARE_API_TOKEN", "").strip()
    if not account_id:
        raise RuntimeError("CLOUDFLARE_ACCOUNT_ID is not set")
    if not api_token:
        raise RuntimeError("CLOUDFLARE_API_TOKEN is not set")

    db = D1Database.from_env(cfg)
    cf_client = Cloudflare(api_token=api_token)
    log = logger.bind(image_id="-", tool="load_item_vectors")
    if not args.dry_run:
        ensure_item_vector_index(
            cfg=cfg,
            cf_client=cf_client,
            account_id=account_id,
            log=log,
        )
    embedder = Embedder(
        cfg.ingestion.embedding_model,
        cfg.ingestion.embedding_dim,
        log,
        image_max_dimension=cfg.ingestion.embedding_image_max_dimension,
        device=cfg.ingestion.embedding_device,
    )
    stats = upsert_distinct_item_vectors(
        cfg=cfg,
        db=db,
        cf_client=cf_client,
        account_id=account_id,
        embedder=embedder,
        log=log,
        dry_run=args.dry_run,
    )
    logger.info(
        "item vector ingestion complete total_items={} upserted_items={} "
        "skipped_items={} elapsed_seconds={}",
        stats.total_items,
        stats.upserted_items,
        stats.skipped_items,
        stats.elapsed_seconds,
    )


if __name__ == "__main__":
    main()
