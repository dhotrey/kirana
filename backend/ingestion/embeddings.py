# from __future__ import annotations


class Embedder:
    def __init__(self, model_name: str, dimensions: int, log) -> None:
        from sentence_transformers import SentenceTransformer

        if dimensions <= 0:
            raise ValueError("dimensions must be > 0")

        self.model_name = model_name
        self.model = SentenceTransformer(self.model_name)
        self.dimensions = dimensions
        self.log = log

    def embed(self, text: str) -> list[float]:
        self.log.debug(f"embedding text: {text}")
        vector = self.model.encode(
            text,
            normalize_embeddings=True,
            truncate_dim=self.dimensions,  # truncate using MRL instead of naive truncation
        )
        self.log.debug("Embedded successfully")
        return vector.tolist()
