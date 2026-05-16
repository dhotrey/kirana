from __future__ import annotations

import pytest

from tools.finance import validate_finance_sql
from utils.db.d1 import extract_d1_query_rows, extract_d1_rows


class D1QueryResult:
    def __init__(self, results):
        self.results = results


class D1Page:
    def __init__(self, result):
        self.result = result


def test_validate_finance_sql_allows_receipt_month_sum():
    sql = validate_finance_sql(
        """
        SELECT
            SUM(total_cents) AS total_cents,
            ROUND(SUM(total_cents) / 100.0, 2) AS total_dollars
        FROM receipts
        WHERE date >= '2026-03-01' AND date < '2026-04-01'
        """
    )

    assert "SUM(total_cents)" in sql
    assert "total_dollars" in sql


def test_validate_finance_sql_allows_splitwise_share_views():
    sql = validate_finance_sql(
        """
        SELECT
            SUM(my_share_cents) AS total_cents,
            ROUND(SUM(my_share_cents) / 100.0, 2) AS total_dollars
        FROM me_expenses
        WHERE date >= '2026-03-01' AND date < '2026-04-01'
        """
    )

    assert "me_expenses" in sql


def test_validate_finance_sql_rejects_receipt_splitwise_join():
    with pytest.raises(ValueError, match="Do not combine receipts"):
        validate_finance_sql(
            """
            SELECT
                r.id,
                r.store_name,
                e.description,
                e.my_share_cents
            FROM receipts r
            JOIN me_expenses e ON r.date = e.date
            WHERE r.date = '2026-04-18'
            """
        )


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM receipts",
        "SELECT * FROM receipts; DROP TABLE splits",
        "SELECT * FROM users",
        "PRAGMA table_info(receipts)",
        "SELECT * FROM receipts -- bypass",
    ],
)
def test_validate_finance_sql_rejects_unsafe_or_unknown_sql(sql):
    with pytest.raises(ValueError):
        validate_finance_sql(sql)


def test_extract_d1_rows_handles_cloudflare_page_shape():
    result = D1Page([D1QueryResult([{"total_cents": 12345, "receipt_count": 3}])])

    assert extract_d1_rows(result) == [{"total_cents": 12345, "receipt_count": 3}]


def test_extract_d1_query_rows_returns_columns_and_tuples():
    result = D1Page([D1QueryResult([{"total_cents": 12345, "receipt_count": 3}])])

    rows = extract_d1_query_rows(result)

    assert rows.columns == ["total_cents", "receipt_count"]
    assert rows.rows == [(12345, 3)]
    assert rows.as_dicts() == [{"total_cents": 12345, "receipt_count": 3}]
