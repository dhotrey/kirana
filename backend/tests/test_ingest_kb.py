import pytest

from ingest_kb import (
    SPLITWISE_INSERT_BATCH_SIZE,
    SPLITWISE_INSERT_COLUMNS,
    clean_splitwise_data,
    money_to_cents,
    prepare_insert,
    prepare_insert_batches,
    splitwise_source_row_hash,
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
    source_row = (
        "2026-02-08",
        "Changi",
        "General",
        "28.35",
        "AUD",
        "-9.45",
        "18.90",
        "-9.45",
    )

    assert clean_splitwise_data(rows) == [
        [
            splitwise_source_row_hash(source_row, 1),
            "2026-02-08",
            "Changi",
            "General",
            2835,
            "AUD",
            -945,
            1890,
            -945,
        ]
    ]


def test_clean_splitwise_data_keeps_repeated_source_rows_distinct():
    row = ["2026-02-08", "Changi", "General", "28.35", "AUD", "-9.45", "18.90", "-9.45"]

    cleaned_rows = clean_splitwise_data([row, row])

    assert cleaned_rows[0][0] == splitwise_source_row_hash(tuple(row), 1)
    assert cleaned_rows[1][0] == splitwise_source_row_hash(tuple(row), 2)
    assert cleaned_rows[0][1:] == cleaned_rows[1][1:]


def test_clean_splitwise_data_rejects_malformed_rows_before_insert():
    with pytest.raises(ValueError, match="expected 8"):
        clean_splitwise_data(
            [["2026-02-08", "Changi", "General", "28.35", "AUD", "-9.45"]]
        )

    with pytest.raises(ValueError, match="unexpected extra columns"):
        clean_splitwise_data(
            [
                [
                    "2026-02-08",
                    "Changi",
                    "General",
                    "28.35",
                    "AUD",
                    "-9.45",
                    "18.90",
                    "-9.45",
                    "extra",
                ]
            ]
        )


def test_prepare_insert_builds_batch_insert_statement():
    row1 = (
        "2026-02-08",
        "Changi",
        "General",
        "28.35",
        "AUD",
        "-9.45",
        "18.90",
        "-9.45",
    )
    row2 = (
        "2026-02-08",
        "Starbucks",
        "Dining out",
        "5.00",
        "AUD",
        "-5.00",
        "0",
        "5.00",
    )
    cleaned_rows = [
        [splitwise_source_row_hash(row1, 1), *row1[:3], 2835, row1[4], -945, 1890, -945],
        [splitwise_source_row_hash(row2, 1), *row2[:3], 500, row2[4], -500, 0, 500],
    ]

    sql, params = prepare_insert(cleaned_rows)

    assert sql == (
        "INSERT OR IGNORE INTO splits "
        "(source_row_hash, date, description, category, cost_cents, currency, me_cents, "
        "roommate1_cents, roommate2_cents)\n"
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?), (?, ?, ?, ?, ?, ?, ?, ?, ?);"
    )
    assert params == [
        splitwise_source_row_hash(row1, 1),
        "2026-02-08",
        "Changi",
        "General",
        "2835",
        "AUD",
        "-945",
        "1890",
        "-945",
        splitwise_source_row_hash(row2, 1),
        "2026-02-08",
        "Starbucks",
        "Dining out",
        "500",
        "AUD",
        "-500",
        "0",
        "500",
    ]


def test_prepare_insert_rejects_empty_data():
    with pytest.raises(ValueError, match="no rows"):
        prepare_insert([])


def test_prepare_insert_batches_keeps_batches_under_d1_variable_limit():
    row = [
        splitwise_source_row_hash(
            ("2026-02-08", "Changi", "General", "28.35", "AUD", "-9.45", "18.90", "-9.45"),
            1,
        ),
        "2026-02-08",
        "Changi",
        "General",
        2835,
        "AUD",
        -945,
        1890,
        -945,
    ]
    cleaned_rows = [row] * (SPLITWISE_INSERT_BATCH_SIZE + 1)

    batches = prepare_insert_batches(cleaned_rows)

    assert len(batches) == 2
    assert len(batches[0][1]) == SPLITWISE_INSERT_BATCH_SIZE * len(SPLITWISE_INSERT_COLUMNS)
    assert len(batches[1][1]) == len(SPLITWISE_INSERT_COLUMNS)


def test_prepare_insert_batches_rejects_invalid_batch_size():
    with pytest.raises(ValueError, match="Batch size"):
        prepare_insert_batches(
            [
                [
                    splitwise_source_row_hash(
                        (
                            "2026-02-08",
                            "Changi",
                            "General",
                            "28.35",
                            "AUD",
                            "-9.45",
                            "18.90",
                            "-9.45",
                        ),
                        1,
                    ),
                    "2026-02-08",
                    "Changi",
                    "General",
                    2835,
                    "AUD",
                    -945,
                    1890,
                    -945,
                ]
            ],
            0,
        )


def test_prepare_insert_rejects_wrong_width_cleaned_rows():
    with pytest.raises(ValueError, match="expected 9"):
        prepare_insert([["2026-02-08", "Changi", "General", 2835, "AUD", -945, 1890, -945]])
