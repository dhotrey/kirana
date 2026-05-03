from __future__ import annotations

from typing import Any

import numpy as np


class Embedder:
    def __init__(self, model_name: str, dimensions: int) -> None:
        if dimensions <= 0:
            raise ValueError("dimensions must be > 0")
        self.model_name = model_name
        self.dimensions = dimensions
        self._model: Any | None = None

    def _get_model(self) -> Any:
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self.model_name)
        return self._model

    def embed(self, text: str) -> list[float]:
        vector = self._get_model().encode(text, normalize_embeddings=True)
        array = np.asarray(vector, dtype=float)
        truncated = array[: self.dimensions]
        norm = np.linalg.norm(truncated)
        if norm:
            truncated = truncated / norm
        return truncated.tolist()
