import sys
import types

import numpy as np

from ingestion.embeddings import Embedder


def test_embedder_truncates_and_normalizes_without_loading_real_model(monkeypatch):
    class FakeSentenceTransformer:
        def __init__(self, model_name: str) -> None:
            self.model_name = model_name

        def encode(self, text: str, normalize_embeddings: bool = True):
            return np.ones(4096)

    fake_module = types.SimpleNamespace(SentenceTransformer=FakeSentenceTransformer)
    monkeypatch.setitem(sys.modules, "sentence_transformers", fake_module)

    vector = Embedder("fake-model", 1536).embed("text")

    assert len(vector) == 1536
    assert np.isclose(np.linalg.norm(vector), 1.0)
