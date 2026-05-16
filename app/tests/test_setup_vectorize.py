from __future__ import annotations

from types import SimpleNamespace

from pydantic import SecretStr

from setup import setup_vectorize, setup_vectorize_metadata_indices
from tests.test_vectorize_tools import _cfg


class FakeMetadataIndex:
    def __init__(self) -> None:
        self.creates: list[dict] = []

    def create(self, **kwargs):
        self.creates.append(kwargs)
        return SimpleNamespace(
            mutation_id=f"{kwargs['index_name']}:{kwargs['property_name']}"
        )


class FakeIndexes:
    def __init__(self) -> None:
        self.creates: list[dict] = []
        self.metadata_index = FakeMetadataIndex()

    def create(self, **kwargs):
        self.creates.append(kwargs)
        return SimpleNamespace(config=kwargs["config"])


def test_setup_vectorize_creates_receipt_and_item_indexes():
    indexes = FakeIndexes()
    cf_client = SimpleNamespace(vectorize=SimpleNamespace(indexes=indexes))

    setup_vectorize(cf_client, SecretStr("account"), _cfg())

    assert [call["name"] for call in indexes.creates] == [
        "kirana-reciept-summaries",
        "kirana-receipt-items",
    ]
    assert [call["config"] for call in indexes.creates] == [
        {"dimensions": 1536, "metric": "cosine"},
        {"dimensions": 1536, "metric": "cosine"},
    ]


def test_setup_vectorize_metadata_indices_include_item_name_index():
    indexes = FakeIndexes()
    cf_client = SimpleNamespace(vectorize=SimpleNamespace(indexes=indexes))

    setup_vectorize_metadata_indices(cf_client, SecretStr("account"), _cfg())

    assert [
        (call["index_name"], call["property_name"], call["index_type"])
        for call in indexes.metadata_index.creates
    ] == [
        ("kirana-reciept-summaries", "receipt_id", "number"),
        ("kirana-reciept-summaries", "store_name", "string"),
        ("kirana-reciept-summaries", "date", "number"),
        ("kirana-receipt-items", "item_name", "string"),
    ]
