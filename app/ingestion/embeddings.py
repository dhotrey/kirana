from __future__ import annotations

import time
from contextlib import nullcontext
from io import BytesIO
from typing import Any

import logfire
from PIL import Image

from utils.observability import logfire_enabled

DEFAULT_IMAGE_EMBED_DIMENSION = 256
_MODEL_CACHE: dict[tuple[str, str | None], Any] = {}


def _span(name: str, **attributes):
    if not logfire_enabled():
        return nullcontext()
    return logfire.span(name, **attributes)


class Embedder:
    def __init__(
        self,
        model_name: str,
        dimensions: int,
        log,
        *,
        image_max_dimension: int = DEFAULT_IMAGE_EMBED_DIMENSION,
        device: str | None = None,
    ) -> None:
        if dimensions <= 0:
            raise ValueError("dimensions must be > 0")
        if image_max_dimension <= 0:
            raise ValueError("image_max_dimension must be > 0")

        self.model_name = model_name
        self.dimensions = dimensions
        self.image_max_dimension = image_max_dimension
        self.device = (
            device.strip() if isinstance(device, str) and device.strip() else None
        )
        self.log = log
        self.model = self._load_model()

    def _load_model(self):
        cache_key = (self.model_name, self.device)
        cached = _MODEL_CACHE.get(cache_key)
        if cached is not None:
            self.log.debug(
                "embedding model cache hit "
                f"model={self.model_name} device={self.device or 'auto'}"
            )
            return cached

        from sentence_transformers import SentenceTransformer

        started_at = time.perf_counter()
        with _span(
            "embedding.model_load",
            model_name=self.model_name,
            device=self.device or "auto",
        ) as span:
            if self.device:
                model = SentenceTransformer(self.model_name, device=self.device)
            else:
                model = SentenceTransformer(self.model_name)
            elapsed_ms = round((time.perf_counter() - started_at) * 1000, 3)
            if span is not None and logfire_enabled():
                span.set_attributes({"elapsed_ms": elapsed_ms, "cache_hit": False})
        self.log.info(
            "embedding model loaded "
            f"model={self.model_name} device={self.device or 'auto'} "
            f"elapsed_ms={elapsed_ms}"
        )
        _MODEL_CACHE[cache_key] = model
        return model

    def embed(self, text: str) -> list[float]:
        started_at = time.perf_counter()
        self.log.debug(f"embedding text: {text}")
        with _span(
            "embedding.text",
            model_name=self.model_name,
            dimensions=self.dimensions,
            text_chars=len(text),
        ) as span:
            vector = self.model.encode(
                text,
                normalize_embeddings=True,
                truncate_dim=self.dimensions,  # truncate using MRL instead of naive truncation
            )
            elapsed_ms = round((time.perf_counter() - started_at) * 1000, 3)
            values = _vector_to_list(vector)
            if span is not None and logfire_enabled():
                span.set_attributes(
                    {"elapsed_ms": elapsed_ms, "output_dimensions": len(values)}
                )
        self.log.debug(f"Embedded text successfully elapsed_ms={elapsed_ms}")
        return values

    def embed_image(self, data: bytes) -> list[float]:
        started_at = time.perf_counter()
        self.log.debug(f"embedding image bytes={len(data)}")
        with _span(
            "embedding.image",
            model_name=self.model_name,
            dimensions=self.dimensions,
            image_bytes=len(data),
            max_dimension=self.image_max_dimension,
        ) as span:
            with _span("embedding.image.decode", image_bytes=len(data)) as decode_span:
                decode_started_at = time.perf_counter()
                with Image.open(BytesIO(data)) as image:
                    original_size = image.size
                    if max(original_size) > self.image_max_dimension:
                        image.draft(
                            "RGB",
                            (self.image_max_dimension, self.image_max_dimension),
                        )
                    image.load()
                    decoded_size = image.size
                    decode_ms = round(
                        (time.perf_counter() - decode_started_at) * 1000, 3
                    )
                    if decode_span is not None and logfire_enabled():
                        decode_span.set_attributes(
                            {
                                "elapsed_ms": decode_ms,
                                "original_width": original_size[0],
                                "original_height": original_size[1],
                                "decoded_width": decoded_size[0],
                                "decoded_height": decoded_size[1],
                                "mode": image.mode,
                            }
                        )
                    with _span(
                        "embedding.image.prepare",
                        original_width=original_size[0],
                        original_height=original_size[1],
                        max_dimension=self.image_max_dimension,
                    ) as prepare_span:
                        prepare_started_at = time.perf_counter()
                        prepared_image = prepare_image_for_embedding(
                            image, self.image_max_dimension
                        )
                        prepare_ms = round(
                            (time.perf_counter() - prepare_started_at) * 1000, 3
                        )
                        if prepare_span is not None and logfire_enabled():
                            prepare_span.set_attributes(
                                {
                                    "elapsed_ms": prepare_ms,
                                    "prepared_width": prepared_image.size[0],
                                    "prepared_height": prepared_image.size[1],
                                    "resized": prepared_image.size != original_size,
                                    "decoder_downsampled": decoded_size != original_size,
                                }
                            )

            with _span(
                "embedding.image.encode",
                prepared_width=prepared_image.size[0],
                prepared_height=prepared_image.size[1],
            ) as encode_span:
                encode_started_at = time.perf_counter()
                vector = self.model.encode(
                    prepared_image,
                    normalize_embeddings=True,
                    truncate_dim=self.dimensions,
                )
                encode_ms = round((time.perf_counter() - encode_started_at) * 1000, 3)
                values = _vector_to_list(vector)
                if encode_span is not None and logfire_enabled():
                    encode_span.set_attributes(
                        {
                            "elapsed_ms": encode_ms,
                            "output_dimensions": len(values),
                        }
                    )

            elapsed_ms = round((time.perf_counter() - started_at) * 1000, 3)
            if span is not None and logfire_enabled():
                span.set_attributes(
                    {
                        "elapsed_ms": elapsed_ms,
                        "decode_ms": decode_ms,
                        "prepare_ms": prepare_ms,
                        "encode_ms": encode_ms,
                        "original_width": original_size[0],
                        "original_height": original_size[1],
                        "decoded_width": decoded_size[0],
                        "decoded_height": decoded_size[1],
                        "prepared_width": prepared_image.size[0],
                        "prepared_height": prepared_image.size[1],
                        "decoder_downsampled": decoded_size != original_size,
                        "output_dimensions": len(values),
                    }
                )
        self.log.info(
            "embedded image "
            f"bytes={len(data)} original={original_size[0]}x{original_size[1]} "
            f"decoded={decoded_size[0]}x{decoded_size[1]} "
            f"prepared={prepared_image.size[0]}x{prepared_image.size[1]} "
            f"decode_ms={decode_ms} prepare_ms={prepare_ms} encode_ms={encode_ms} "
            f"elapsed_ms={elapsed_ms}"
        )
        return values


def prepare_image_for_embedding(
    image: Image.Image, max_dimension: int = DEFAULT_IMAGE_EMBED_DIMENSION
) -> Image.Image:
    if max_dimension <= 0:
        raise ValueError("max_dimension must be > 0")

    prepared = image.convert("RGB")
    if max(prepared.size) <= max_dimension:
        return prepared.copy()

    prepared.thumbnail((max_dimension, max_dimension), Image.Resampling.LANCZOS)
    return prepared.copy()


def _vector_to_list(vector: Any) -> list[float]:
    if hasattr(vector, "tolist"):
        return vector.tolist()
    return list(vector)
