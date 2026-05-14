from __future__ import annotations

import pytest
from PIL import Image

from ingestion.embeddings import prepare_image_for_embedding


def test_prepare_image_for_embedding_downscales_large_image():
    image = Image.new("RGB", (4000, 2000), color="white")

    prepared = prepare_image_for_embedding(image, max_dimension=1280)

    assert prepared.size == (1280, 640)
    assert prepared.mode == "RGB"


def test_prepare_image_for_embedding_does_not_upscale_small_image():
    image = Image.new("RGBA", (640, 480), color="white")

    prepared = prepare_image_for_embedding(image, max_dimension=1280)

    assert prepared.size == (640, 480)
    assert prepared.mode == "RGB"


def test_prepare_image_for_embedding_rejects_invalid_dimension():
    image = Image.new("RGB", (640, 480), color="white")

    with pytest.raises(ValueError):
        prepare_image_for_embedding(image, max_dimension=0)
