import sqlite3

import pytest

from ingest_kb import (
    SPLITWISE_INSERT_BATCH_SIZE,
    clean_splitwise_data,
    money_to_cents,
    prepare_insert,
    prepare_insert_batches,
)


def test_money_to_cents_converts_decimal_dollars_to_integer_cents():
    assert money_to_cents("25.00") == 2500
    assert money_to_cents("-9.45") == -945
    assert money_to_cents("1.005") == 101


def test_clean_splitwise_data_converts_financial_columns_to_cents():
    rows = [
        [],
        ["2026-02-08", "Changi ", "General", "28.35", "AUD", "-9.45", "18.90", "-9.45"],
        ["2026-04-26", "Total balance", " ", " ", "AUD", "-5.71", "-28.13", "33.84"],
    ]

    assert clean_splitwise_data(rows) == [
        ["2026-02-08", "Changi", "General", 2835, "AUD", -945, 1890, -945]
    ]


def test_prepare_insert_builds_batch_insert_statement():
    cleaned_rows = [
        ["2026-02-08", "Changi", "General", 2835, "AUD", -945, 1890, -945],
        ["2026-02-08", "Starbucks", "Dining out", 500, "AUD", -500, 0, 500],
    ]

    sql, params = prepare_insert(cleaned_rows)

    assert sql == (
        "WITH deduped (date, description, category, cost_cents, currency, "
        "me_cents, roommate1_cents, roommate2_cents) AS (\n"
        "    VALUES (?, ?, ?, ?, ?, ?, ?, ?), (?, ?, ?, ?, ?, ?, ?, ?)\n"
        ")\n"
        "INSERT INTO splits (date, description, category, cost_cents, "
        "currency, me_cents, roommate1_cents, roommate2_cents)\n"
        "SELECT deduped.date, deduped.description, deduped.category, "
        "deduped.cost_cents, deduped.currency, deduped.me_cents, "
        "deduped.roommate1_cents, deduped.roommate2_cents\n"
        "FROM deduped\n"
        "WHERE NOT EXISTS (\n"
        "    SELECT 1\n"
        "    FROM splits\n"
        "    WHERE splits.date = deduped.date AND "
        "splits.description = deduped.description AND "
        "splits.category = deduped.category AND "
        "splits.cost_cents = deduped.cost_cents AND "
        "splits.currency = deduped.currency AND "
        "splits.me_cents = deduped.me_cents AND "
        "splits.roommate1_cents = deduped.roommate1_cents AND "
        "splits.roommate2_cents = deduped.roommate2_cents\n"
        ");"
    )
    assert params == [
        "2026-02-08",
        "Changi",
        "General",
        "2835",
        "AUD",
        "-945",
        "1890",
        "-945",
        "2026-02-08",
        "Starbucks",
        "Dining out",
        "500",
        "AUD",
        "-500",
        "0",
        "500",
    ]


def test_prepare_insert_is_idempotent_when_replayed_against_existing_rows():
    cleaned_rows = [
        ["2026-02-08", "Changi", "General", 2835, "AUD", -945, 1890, -945],
        ["2026-02-08", "Starbucks", "Dining out", 500, "AUD", -500, 0, 500],
    ]
    sql, params = prepare_insert(cleaned_rows)

    db = sqlite3.connect(":memory:")
    db.execute(
        """
        CREATE TABLE splits (
            id INTEGER PRIMARY KEY,
            date TEXT NOT NULL,
            description TEXT NOT NULL,
            category TEXT,
            cost_cents INTEGER NOT NULL,
            currency TEXT NOT NULL,
            me_cents INTEGER NOT NULL,
            roommate1_cents INTEGER NOT NULL,
            roommate2_cents INTEGER NOT NULL
        );
        """
    )

    db.execute(sql, params)
    db.execute(sql, params)

    assert db.execute("SELECT COUNT(*) FROM splits").fetchone() == (2,)


def test_clean_splitwise_data_rejects_rows_with_unexpected_column_count():
    with pytest.raises(ValueError, match="expected 8"):
        clean_splitwise_data(
            [["2026-02-08", "Changi", "General", "28.35", "AUD", "-9.45", "18.90"]]
        )


def test_prepare_insert_rejects_rows_with_unexpected_column_count():
    with pytest.raises(ValueError, match="expected 8"):
        prepare_insert(
            [["2026-02-08", "Changi", "General", 2835, "AUD", -945, 1890]]
        )


def test_prepare_insert_rejects_empty_data():
    with pytest.raises(ValueError, match="no rows"):
        prepare_insert([])


def test_prepare_insert_batches_keeps_batches_under_d1_variable_limit():
    row = ["2026-02-08", "Changi", "General", 2835, "AUD", -945, 1890, -945]
    cleaned_rows = [row] * (SPLITWISE_INSERT_BATCH_SIZE + 1)

    batches = prepare_insert_batches(cleaned_rows)

    assert len(batches) == 2
    assert len(batches[0][1]) == SPLITWISE_INSERT_BATCH_SIZE * 8
    assert len(batches[1][1]) == 8


def test_prepare_insert_batches_rejects_invalid_batch_size():
    with pytest.raises(ValueError, match="Batch size"):
        prepare_insert_batches(
            [["2026-02-08", "Changi", "General", 2835, "AUD", -945, 1890, -945]],
            0,
        )
