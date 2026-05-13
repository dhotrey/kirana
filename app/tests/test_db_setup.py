from __future__ import annotations

from utils.db.db_setup import splitwise_expense_views_sql


def test_splitwise_expense_views_define_adjusted_share_columns():
    assert "CREATE VIEW IF NOT EXISTS me_expenses" in splitwise_expense_views_sql
    assert "my_share_cents" in splitwise_expense_views_sql
    assert "CREATE VIEW IF NOT EXISTS roommate1_expenses" in splitwise_expense_views_sql
    assert "roommate1_share_cents" in splitwise_expense_views_sql
    assert "CREATE VIEW IF NOT EXISTS roommate2_expenses" in splitwise_expense_views_sql
    assert "roommate2_share_cents" in splitwise_expense_views_sql
