"""Fase 4 — da fonte à Bronze.

Ponte (fundação, T020): o gerador compartilhado escreve o *armazém das fontes* (fontes.duckdb, o "mundo de fora")
e a stack copia o que as fontes entregaram para `bronze_raw` no lake, reconstruindo a Bronze. Na US1 a cópia vira
a carga declarativa do dlt a partir das APIs simuladas; `bridge_load` continua como carga de referência nos testes.
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from unittest import mock

import duckdb

import agentready.db as _db
from agentready import generate

# Capturado na importação: nos testes, o conftest troca `agentready.db.connect` pela conexão da stack, mas o
# armazém das fontes é um DuckDB comum, aberto pelo conector original.
_SHARED_CONNECT = _db.connect

# Tabelas de bronze_raw por tabela da Bronze (as conversões chegam de duas fontes: ga4 e Meta).
RAW = {"ad_spend": ("ad_spend",), "campaigns": ("campaigns",),
       "conversions": ("conversions__ga4", "conversions__meta_capi")}
DLT_COLUMNS = ("_dlt_load_id", "_dlt_id")


def store_path() -> str:
    return os.environ.get("STACK_SOURCES_DB", "/opt/stack-data/upstream/fontes.duckdb")


@contextmanager
def shared_store(path: str):
    """Faz o código compartilhado (gerador, incidentes) escrever no armazém das fontes, não no lake."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with mock.patch.object(_db, "DB_PATH", Path(path)), mock.patch.object(generate, "connect", _SHARED_CONNECT):
        yield


def store_generate(path: str, now: datetime | None = None) -> dict:
    with shared_store(path):
        return generate.generate(now)


def store_connect(path: str) -> duckdb.DuckDBPyConnection:
    with shared_store(path):
        return _SHARED_CONNECT()


def _columns(con, schema: str, table: str) -> list[str]:
    return [r[0] for r in con.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_catalog=current_database() "
        "AND table_schema=? AND table_name=? ORDER BY ordinal_position", [schema, table]).fetchall()]


def _raw_select(con, raw: str) -> str:
    dlt = [c for c in DLT_COLUMNS if c in _columns(con, "bronze_raw", raw)]
    return f"SELECT * {'EXCLUDE (' + ', '.join(dlt) + ')' if dlt else ''} FROM bronze_raw.{raw}"


def rebuild_bronze(con, tables: tuple[str, ...] = tuple(RAW)) -> None:
    """Bronze = tabelas (não views): o código compartilhado e os testes das Fases 1–3 alteram a Bronze no lugar."""
    for t in tables:
        parts = [_raw_select(con, r) for r in RAW[t] if _columns(con, "bronze_raw", r)]
        if parts:
            con.execute(f"CREATE OR REPLACE TABLE bronze.{t} AS " + " UNION ALL BY NAME ".join(parts))


def bridge_load(con, path: str) -> None:
    """Cópia de referência: o que as fontes entregaram (armazém das fontes) → bronze_raw → Bronze, numa transação."""
    con.execute(f"ATTACH '{path}' AS fontes (READ_ONLY)")
    try:
        con.execute("BEGIN")
        con.execute("CREATE OR REPLACE TABLE bronze_raw.ad_spend AS FROM fontes.bronze.ad_spend")
        con.execute("CREATE OR REPLACE TABLE bronze_raw.campaigns AS FROM fontes.bronze.campaigns")
        con.execute("CREATE OR REPLACE TABLE bronze_raw.conversions__ga4 AS "
                    "FROM fontes.bronze.conversions WHERE source = 'ga4'")
        con.execute("CREATE OR REPLACE TABLE bronze_raw.conversions__meta_capi AS "
                    "FROM fontes.bronze.conversions WHERE source = 'meta_capi'")
        # O backlog da Meta acompanha a ponte: o `generate.backfill_meta` compartilhado roda sobre o lake nos testes.
        con.execute("CREATE OR REPLACE TABLE meta.upstream_backlog AS FROM fontes.meta.upstream_backlog")
        rebuild_bronze(con)
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    finally:
        con.execute("DETACH fontes")


def reset_stack(con, now: datetime) -> None:
    """Lake e estado operacional zerados; o estado vivo das campanhas semeado pelo código compartilhado."""
    from agentready_stack import warehouse
    warehouse.reset(con)
    generate.create_ops_tables(con)
    generate.seed_live_state(con, now)
