from __future__ import annotations

from types import SimpleNamespace

from ingestion.items_vectorize import (
    build_item_vector,
    ensure_item_vector_index,
    fetch_distinct_item_names,
    item_vector_id,
    normalize_item_name,
    upsert_distinct_item_vectors,
)
from tests.test_vectorize_tools import _cfg


def test_normalize_item_name_collapses_whitespace():
    assert normalize_item_name("  Baby   Spinach  ") == "Baby Spinach"


def test_item_vector_id_is_case_insensitive():
    assert item_vector_id("Baby Spinach") == item_vector_id("baby spinach")


def test_build_item_vector_stores_item_name_metadata():
    vector = build_item_vector("Baby Spinach", [0.1, 0.2])

    assert vector["id"].startswith("item:")
    assert vector["values"] == [0.1, 0.2]
    assert vector["metadata"] == {"item_name": "Baby Spinach"}


def test_fetch_distinct_item_names_normalizes_and_dedupes():
    class FakeDb:
        def query_rows(self, sql):
            self.sql = sql
            return SimpleNamespace(
                as_dicts=lambda: [
                    {"item_name": " Baby   Spinach "},
                    {"item_name": "baby spinach"},
                    {"item_name": ""},
                    {"item_name": None},
                    {"item_name": "Milk"},
                ]
            )

    assert fetch_distinct_item_names(FakeDb()) == ["Baby Spinach", "Milk"]


def test_upsert_distinct_item_vectors_upserts_one_at_a_time():
    class FakeDb:
        def query_rows(self, sql):
            return SimpleNamespace(
                as_dicts=lambda: [
                    {"item_name": "Apple"},
                    {"item_name": "Banana"},
                ]
            )

    class FakeEmbedder:
        def embed(self, text):
            return [1.0] * 1536

    class FakeIndexes:
        def __init__(self):
            self.upserts = []

        def upsert(self, **kwargs):
            self.upserts.append(kwargs)

    indexes = FakeIndexes()
    cf_client = SimpleNamespace(vectorize=SimpleNamespace(indexes=indexes))
    stats = upsert_distinct_item_vectors(
        cfg=_cfg(),
        db=FakeDb(),
        cf_client=cf_client,
        account_id="account",
        embedder=FakeEmbedder(),
        log=SimpleNamespace(info=lambda *args, **kwargs: None),
    )

    assert stats.total_items == 2
    assert stats.upserted_items == 2
    assert [call["index_name"] for call in indexes.upserts] == [
        "kirana-receipt-items",
        "kirana-receipt-items",
    ]
    assert [len(call["body"]["vectors"]) for call in indexes.upserts] == [1, 1]
    assert [
        call["body"]["vectors"][0]["metadata"]["item_name"] for call in indexes.upserts
    ] == ["Apple", "Banana"]


def test_upsert_distinct_item_vectors_deletes_written_vectors_on_failure():
    class FakeDb:
        def query_rows(self, sql):
            return SimpleNamespace(
                as_dicts=lambda: [
                    {"item_name": "Apple"},
                    {"item_name": "Banana"},
                ]
            )

    class FakeEmbedder:
        def embed(self, text):
            return [1.0] * 1536

    class FakeIndexes:
        def __init__(self):
            self.upserts = 0
            self.deleted_ids = None

        def upsert(self, **kwargs):
            self.upserts += 1
            if self.upserts == 2:
                raise RuntimeError("bad vector write")

        def delete_by_ids(self, **kwargs):
            self.deleted_ids = kwargs["ids"]

    indexes = FakeIndexes()
    cf_client = SimpleNamespace(vectorize=SimpleNamespace(indexes=indexes))

    try:
        upsert_distinct_item_vectors(
            cfg=_cfg(),
            db=FakeDb(),
            cf_client=cf_client,
            account_id="account",
            embedder=FakeEmbedder(),
            log=SimpleNamespace(
                info=lambda *args, **kwargs: None,
                warning=lambda *args, **kwargs: None,
            ),
        )
    except RuntimeError as exc:
        assert str(exc) == "bad vector write"
    else:
        raise AssertionError("expected vector write failure")

    assert indexes.deleted_ids == [item_vector_id("Apple")]


def test_ensure_item_vector_index_creates_missing_index_and_metadata():
    class NotFound(Exception):
        status_code = 404

    class FakeMetadataIndex:
        def __init__(self):
            self.creates = []

        def create(self, **kwargs):
            self.creates.append(kwargs)

    class FakeIndexes:
        def __init__(self):
            self.creates = []
            self.metadata_index = FakeMetadataIndex()

        def get(self, **kwargs):
            raise NotFound("index was not found")

        def create(self, **kwargs):
            self.creates.append(kwargs)

    indexes = FakeIndexes()
    cf_client = SimpleNamespace(vectorize=SimpleNamespace(indexes=indexes))

    ensure_item_vector_index(
        cfg=_cfg(),
        cf_client=cf_client,
        account_id="account",
        log=SimpleNamespace(info=lambda *args, **kwargs: None),
    )

    assert indexes.creates == [
        {
            "account_id": "account",
            "name": "kirana-receipt-items",
            "config": {"dimensions": 1536, "metric": "cosine"},
        }
    ]
    assert indexes.metadata_index.creates == [
        {
            "index_name": "kirana-receipt-items",
            "account_id": "account",
            "property_name": "item_name",
            "index_type": "string",
        }
    ]
