from __future__ import annotations

from utils.db.db_setup import splitwise_expense_views_sql
from utils.db.d1 import extract_d1_query_rows


def test_splitwise_expense_views_define_adjusted_share_columns():
    assert "CREATE VIEW IF NOT EXISTS me_expenses" in splitwise_expense_views_sql
    assert "my_share_cents" in splitwise_expense_views_sql
    assert "CREATE VIEW IF NOT EXISTS roommate1_expenses" in splitwise_expense_views_sql
    assert "roommate1_share_cents" in splitwise_expense_views_sql
    assert "CREATE VIEW IF NOT EXISTS roommate2_expenses" in splitwise_expense_views_sql
    assert "roommate2_share_cents" in splitwise_expense_views_sql


def test_extract_d1_query_rows_unwraps_cloudflare_result_envelope():
    result = {
        "result": [
            {
                "meta": {"rows_read": 2},
                "results": [
                    {"item_name": "Apple"},
                    {"item_name": "Banana"},
                ],
                "success": True,
            }
        ],
        "errors": [],
        "messages": [],
        "success": True,
    }

    rows = extract_d1_query_rows(result)

    assert rows.columns == ["item_name"]
    assert rows.as_dicts() == [{"item_name": "Apple"}, {"item_name": "Banana"}]


def test_extract_d1_query_rows_unwraps_stringified_cloudflare_result_envelope():
    result = {
        "result": (
            "[{'meta': {'rows_read': 1}, "
            "'results': [{'item_name': 'Apple'}], "
            "'success': True}]"
        ),
        "errors": "[]",
        "messages": "[]",
        "success": True,
    }

    rows = extract_d1_query_rows(result)

    assert rows.columns == ["item_name"]
    assert rows.as_dicts() == [{"item_name": "Apple"}]
