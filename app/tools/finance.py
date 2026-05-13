from __future__ import annotations

import json
import re
import time
from contextlib import nullcontext

import logfire
from langchain_core.tools import BaseTool, tool
from loguru import logger
from pydantic import BaseModel, Field

from utils.db.d1 import D1Database
from utils.observability import logfire_enabled

ALLOWED_FINANCE_TABLES = {
    "receipts",
    "receipt_items",
    "splits",
    "me_expenses",
    "roommate1_expenses",
    "roommate2_expenses",
}
MAX_RESULT_ROWS = 100

FORBIDDEN_SQL_PATTERNS = re.compile(
    r"\b("
    r"alter|analyze|attach|begin|commit|create|delete|detach|drop|insert|pragma|"
    r"reindex|replace|rollback|update|vacuum"
    r")\b",
    re.IGNORECASE,
)
TABLE_REFERENCE_PATTERN = re.compile(
    r"\b(?:from|join)\s+([a-zA-Z_][a-zA-Z0-9_]*)\b",
    re.IGNORECASE,
)


class FinanceSQLInput(BaseModel):
    sql: str = Field(
        description=(
            "A read-only SQLite SELECT query over receipts, receipt_items, and splits. "
            "Use cents columns for arithmetic, convert money to dollars in SQL, "
            "and alias computed fields clearly."
        )
    )


def validate_finance_sql(sql: str) -> str:
    normalized = sql.strip()
    if not normalized:
        raise ValueError("SQL query cannot be empty")
    if "/*" in normalized or "*/" in normalized or "--" in normalized:
        raise ValueError("SQL comments are not allowed")

    normalized = normalized.removesuffix(";").strip()
    if ";" in normalized:
        raise ValueError("Only one SQL statement is allowed")
    if not re.match(r"^select\b", normalized, re.IGNORECASE):
        raise ValueError("Only SELECT queries are allowed")
    if FORBIDDEN_SQL_PATTERNS.search(normalized):
        raise ValueError("Only read-only SELECT queries are allowed")

    referenced_tables = {
        match.group(1).lower() for match in TABLE_REFERENCE_PATTERN.finditer(normalized)
    }
    if not referenced_tables:
        raise ValueError("Query must reference at least one finance table")
    unknown_tables = referenced_tables - ALLOWED_FINANCE_TABLES
    if unknown_tables:
        raise ValueError(
            "Query can only reference these tables: "
            + ", ".join(sorted(ALLOWED_FINANCE_TABLES))
        )
    return normalized


def _tool_span(tool_name: str, **attributes):
    if not logfire_enabled():
        return nullcontext()
    return logfire.span(f"tool.{tool_name}", tool_name=tool_name, **attributes)


def build_finance_tools(db: D1Database) -> list[BaseTool]:
    @tool(
        "query_finance_db",
        args_schema=FinanceSQLInput,
        description=(
            "Run a validated read-only SQLite SELECT query against the household "
            "finance database. Available tables/views are receipts, receipt_items, "
            "splits, me_expenses, roommate1_expenses, and roommate2_expenses. "
            "Amounts are stored as integer cents; convert result amounts to dollars "
            "in SQL using ROUND(cents_column / 100.0, 2)."
        ),
    )
    def query_finance_db(sql: str) -> str:
        started_at = time.perf_counter()
        logger.info("tool call query_finance_db sql={!r}", sql)
        with _tool_span("query_finance_db", sql=sql) as span:
            try:
                validated_sql = validate_finance_sql(sql)
                result = db.query_rows(validated_sql)
                rows = result.as_dicts()
                response = {
                    "ok": True,
                    "sql": validated_sql,
                    "columns": result.columns,
                    "row_count": len(rows),
                    "rows": rows[:MAX_RESULT_ROWS],
                    "truncated": len(rows) > MAX_RESULT_ROWS,
                }
            except Exception as exc:
                logger.exception("tool call query_finance_db failed sql={!r}", sql)
                response = {"ok": False, "error": str(exc)}

            elapsed_ms = round((time.perf_counter() - started_at) * 1000, 3)
            logger.info(
                "tool call query_finance_db complete ok={} elapsed_ms={}",
                response["ok"],
                elapsed_ms,
            )
            if span is not None and logfire_enabled():
                span.set_attributes(
                    {
                        "success": response["ok"],
                        "elapsed_ms": elapsed_ms,
                        "row_count": response.get("row_count", 0),
                        "error": response.get("error"),
                    }
                )
            return json.dumps(response)

    return [query_finance_db]
