from __future__ import annotations

import argparse
from pathlib import Path

from ingestion.context import build_context
from ingestion.observability import configure_logfire, configure_logging
from ingestion.pipeline import ingest_one
from ingestion.sources.disk import DiskImageSource, from_disk_path
import os
import dotenv
dotenv.load_dotenv()

os.environ["TRANSFORMERS_VERBOSITY"] = "error"
os.environ["TRANSFORMERS_NO_ADVISORY_WARNINGS"] = "1"
os.environ["HF_HUB_OFFLINE"] = "1"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ingest receipt images into Kirana KB")
    parser.add_argument(
        "--config",
        default="config.toml",
        help="Path to backend config.toml",
    )
    parser.add_argument(
        "--image",
        type=Path,
        help="Optional single image path. If omitted, processes receipts_image_dir.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run OCR, summary, embedding and logs, but skip D1/Vectorize/Tigris writes.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    ctx = build_context(args.config)
    
    configure_logging(ctx.cfg)
    configure_logfire()
    ctx = ctx.with_dry_run(True if args.dry_run else None)

    if args.image:
        images = [from_disk_path(args.image)]
    else:
        images = list(DiskImageSource(Path(ctx.cfg.ingestion.receipts_image_dir)))

    total = len(images)
    for idx, image in enumerate(images, start=1):
        ctx.log.info(f"processing receipt {idx}/{total}: {image.image_id}")
        ingest_one(image, ctx)


if __name__ == "__main__":
    main()
