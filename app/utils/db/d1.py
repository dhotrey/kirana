from __future__ import annotations

import os
import ast
import time
from contextlib import nullcontext
from dataclasses import dataclass
from typing import Any

import logfire
from loguru import logger

from utils.observability import logfire_enabled
from utils.types import Config


@dataclass
class D1QueryRows:
    columns: list[str]
    rows: list[tuple[Any, ...]]

    def as_dicts(self) -> list[dict[str, Any]]:
        return [dict(zip(self.columns, row, strict=False)) for row in self.rows]


class D1Database:
    def __init__(
        self,
        *,
        account_id: str,
        api_token: str,
        database_id: str,
        database_name: str,
    ) -> None:
        self.account_id = account_id.strip()
        self.api_token = api_token.strip()
        self.database_id = database_id.strip()
        self.database_name = database_name
        self._client: Any | None = None

    @classmethod
    def from_env(cls, cfg: Config) -> "D1Database":
        return cls(
            account_id=os.environ.get("CLOUDFLARE_ACCOUNT_ID", ""),
            api_token=os.environ.get("CLOUDFLARE_API_TOKEN", ""),
            database_id=os.environ.get("KIRANA_DB_ID", ""),
            database_name=cfg.cloudflare.d1_database_name,
        )

    @property
    def available(self) -> bool:
        return bool(self.account_id and self.api_token and self.database_id)

    def query(self, sql: str, params: list[Any] | None = None) -> list[tuple[Any, ...]]:
        return self.query_rows(sql, params).rows

    def query_rows(self, sql: str, params: list[Any] | None = None) -> D1QueryRows:
        params = params or []
        if not self.available:
            raise RuntimeError(
                "Finance database is unavailable. Set CLOUDFLARE_ACCOUNT_ID, "
                "CLOUDFLARE_API_TOKEN, and KIRANA_DB_ID."
            )

        span = nullcontext()
        if logfire_enabled():
            span = logfire.span(
                "d1.query",
                database_name=self.database_name,
                database_id=self.database_id,
                sql=sql,
                bind_params_count=len(params),
            )

        started_at = time.perf_counter()
        logger.info("d1 query database={} sql={!r}", self.database_name, sql)
        with span as query_span:
            try:
                result = self._cloudflare_client().d1.database.query(
                    account_id=self.account_id,
                    database_id=self.database_id,
                    sql=sql,
                    params=params,
                )
                rows = extract_d1_query_rows(result)
            except Exception as exc:
                elapsed_ms = round((time.perf_counter() - started_at) * 1000, 3)
                logger.exception(
                    "d1 query failed database={} elapsed_ms={} sql={!r}",
                    self.database_name,
                    elapsed_ms,
                    sql,
                )
                if query_span is not None and logfire_enabled():
                    query_span.set_attributes(
                        {
                            "success": False,
                            "elapsed_ms": elapsed_ms,
                            "error": str(exc),
                        }
                    )
                raise

            elapsed_ms = round((time.perf_counter() - started_at) * 1000, 3)
            logger.info(
                "d1 query complete database={} rows={} elapsed_ms={}",
                self.database_name,
                len(rows.rows),
                elapsed_ms,
            )
            if query_span is not None and logfire_enabled():
                query_span.set_attributes(
                    {
                        "success": True,
                        "elapsed_ms": elapsed_ms,
                        "row_count": len(rows.rows),
                        "columns": rows.columns,
                    }
                )
            return rows

    def _cloudflare_client(self) -> Any:
        if self._client is None:
            from cloudflare import Cloudflare

            self._client = Cloudflare(api_token=self.api_token)
        return self._client


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    return str(value)


def _row_to_dict(row: Any) -> dict[str, Any] | None:
    if isinstance(row, dict):
        return {str(key): _jsonable(value) for key, value in row.items()}
    if hasattr(row, "model_dump"):
        dumped = row.model_dump()
        if isinstance(dumped, dict):
            return {str(key): _jsonable(value) for key, value in dumped.items()}
    return None


def extract_d1_rows(result: Any) -> list[dict[str, Any]]:
    pending = [result]
    seen: set[int] = set()
    while pending:
        current = pending.pop(0)
        if current is None:
            continue
        current_id = id(current)
        if current_id in seen:
            continue
        seen.add(current_id)

        if isinstance(current, list):
            rows = [_row_to_dict(item) for item in current]
            if rows and all(row is not None for row in rows):
                dict_rows = [row for row in rows if row is not None]
                if any(
                    {"results", "rows", "result"} & set(row.keys()) for row in dict_rows
                ):
                    pending.extend(current)
                    continue
                return dict_rows
            pending.extend(current)
            continue

        if isinstance(current, dict):
            nested_keys = [
                key for key in ("results", "rows", "result") if key in current
            ]
            if nested_keys:
                for key in nested_keys:
                    nested = current[key]
                    if isinstance(nested, str) and nested[:1] in {"[", "{"}:
                        try:
                            nested = ast.literal_eval(nested)
                        except (SyntaxError, ValueError):
                            pass
                    pending.append(nested)
                continue
            return [{str(key): _jsonable(value) for key, value in current.items()}]

        for attr in ("results", "rows", "result"):
            if hasattr(current, attr):
                pending.append(getattr(current, attr))
                break
        else:
            row = _row_to_dict(current)
            if row is not None:
                nested = row.get("result")
                if isinstance(nested, str) and nested[:1] in {"[", "{"}:
                    try:
                        pending.append(ast.literal_eval(nested))
                        continue
                    except (SyntaxError, ValueError):
                        pass
                return [row]

    return []


def extract_d1_query_rows(result: Any) -> D1QueryRows:
    dict_rows = extract_d1_rows(result)
    columns: list[str] = []
    for row in dict_rows:
        for key in row:
            if key not in columns:
                columns.append(key)

    tuple_rows = [tuple(row.get(column) for column in columns) for row in dict_rows]
    return D1QueryRows(columns=columns, rows=tuple_rows)
