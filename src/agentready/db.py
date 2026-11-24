"""Conexão DuckDB: o 'lakehouse' local com as camadas bronze/silver/gold e o estado operacional."""
from __future__ import annotations

import duckdb

from agentready.settings import DATA_DIR, DB_PATH

SCHEMAS = ("bronze", "silver", "gold", "quarantine", "ops", "meta")


def connect(read_only: bool = False) -> duckdb.DuckDBPyConnection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(DB_PATH), read_only=read_only)
    if not read_only:
        for s in SCHEMAS:
            con.execute(f"CREATE SCHEMA IF NOT EXISTS {s}")
    return con


def rows(con: duckdb.DuckDBPyConnection, sql: str, params: list | None = None) -> list[dict]:
    cur = con.execute(sql, params or [])
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]
