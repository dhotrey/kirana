from __future__ import annotations

import os
import time
from pathlib import Path

import pytest
from loguru import logger
from PIL import Image

from ingestion.embeddings import Embedder, prepare_image_for_embedding
from utils.config import load_config

BENCHMARK_IMAGE_DIR = Path(__file__).parents[2] / "knowledge-base" / "images"
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}


def _benchmark_enabled() -> bool:
    return os.environ.get("KIRANA_RUN_IMAGE_EMBED_BENCHMARK", "").lower() in {
        "1",
        "true",
        "yes",
    }


def _benchmark_images(limit: int = 2) -> list[Path]:
    if not BENCHMARK_IMAGE_DIR.exists():
        return []
    return [
        path
        for path in sorted(BENCHMARK_IMAGE_DIR.iterdir())
        if path.suffix.lower() in IMAGE_EXTENSIONS
    ][:limit]


@pytest.mark.skipif(
    not _benchmark_enabled(),
    reason="Set KIRANA_RUN_IMAGE_EMBED_BENCHMARK=1 to run local image embedding benchmark.",
)
def test_embed_local_knowledge_base_images_benchmark():
    image_paths = _benchmark_images()
    if not image_paths:
        pytest.skip(f"No benchmark images found in {BENCHMARK_IMAGE_DIR}")

    cfg = load_config("config.toml")
    dimensions_to_try = [512, 384, 256]
    summary_rows: list[dict[str, object]] = []

    for max_dimension in dimensions_to_try:
        embedder = Embedder(
            cfg.ingestion.embedding_model,
            cfg.ingestion.embedding_dim,
            logger.bind(image_id=f"bench-{max_dimension}"),
            image_max_dimension=max_dimension,
            device=cfg.ingestion.embedding_device,
        )
        for image_path in image_paths:
            data = image_path.read_bytes()
            with Image.open(image_path) as image:
                original_size = image.size
                prepared_size = prepare_image_for_embedding(image, max_dimension).size

            started_at = time.perf_counter()
            vector = embedder.embed_image(data)
            elapsed_seconds = time.perf_counter() - started_at
            row = {
                "image": image_path.name,
                "bytes": len(data),
                "original_size": original_size,
                "max_dimension": max_dimension,
                "prepared_size": prepared_size,
                "elapsed_seconds": round(elapsed_seconds, 3),
                "vector_dimensions": len(vector),
            }
            summary_rows.append(row)
            print(row)

    assert summary_rows
    assert all(row["vector_dimensions"] == cfg.ingestion.embedding_dim for row in summary_rows)
