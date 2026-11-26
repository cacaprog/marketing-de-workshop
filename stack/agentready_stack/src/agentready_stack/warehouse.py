"""Fase 4 — a conexão da trilha stack: estado operacional no ops.duckdb + camadas de dados no DuckLake.

Uma conexão vê os dois sem mudar uma linha do código compartilhado (pesquisa R2):

- o arquivo principal é o `ops.duckdb`, então o DuckDB chama esse catálogo de `ops` (o nome do arquivo);
- o DuckLake é anexado como `warehouse` e vira o catálogo atual (`USE warehouse`).

Assim `gold.campaign_daily` resolve para `warehouse.gold.campaign_daily` e `ops.campaigns` para o catálogo `ops`
(não existe schema `ops` no lake). O nome `warehouse` mantém os nomes da linhagem da Fase 2.
Os snapshots do lake nunca tocam o estado operacional: orçamentos, change log e aprovações ficam no ops.duckdb.
"""
from __future__ import annotations

import os
from pathlib import Path

import duckdb

LAKE = "warehouse"
# Camadas de dados (versionadas pelo DuckLake). `ops` NUNCA entra aqui (FR-011).
DATA_SCHEMAS = ("bronze_raw", "bronze", "quarantine", "silver", "gold", "meta", "elementary")


class WarehouseError(RuntimeError):
    """Erro de configuração da conexão (mensagem em pt-BR)."""


def _ops_path() -> Path:
    p = Path(os.environ.get("AGENTREADY_DB", "/opt/stack-data/ops.duckdb"))
    if p.stem != "ops":
        raise WarehouseError(f"AGENTREADY_DB deve apontar para um arquivo ops.duckdb (recebi {p}): o nome do "
                             "arquivo vira o catálogo `ops` que o código compartilhado usa (ops.campaigns, ...)")
    return p


def lake_uri() -> str:
    cat = os.environ.get("STACK_LAKE_CATALOG")
    if not cat:
        raise WarehouseError("STACK_LAKE_CATALOG não definido (catálogo do DuckLake: postgres:... ou um arquivo .ducklake)")
    return f"ducklake:{cat}"


def lake_data_path() -> str:
    d = os.environ.get("STACK_LAKE_DATA")
    if not d:
        raise WarehouseError("STACK_LAKE_DATA não definido (pasta dos arquivos Parquet do DuckLake)")
    return d if d.endswith("/") else d + "/"


def configure(con: duckdb.DuckDBPyConnection) -> None:
    """Extensões só da pasta preinstalada na imagem e sem download: uma extensão faltando falha alto, sem rede."""
    ext = os.environ.get("STACK_DUCKDB_EXTENSIONS")
    if ext:
        con.execute(f"SET extension_directory='{ext}'")
        con.execute("SET autoinstall_known_extensions=false")
    con.execute("SET autoload_known_extensions=true")


def connect(read_only: bool = False) -> duckdb.DuckDBPyConnection:
    """ops.duckdb (catálogo `ops`) + DuckLake anexado como `warehouse`, que vira o catálogo atual."""
    ops = _ops_path()
    ops.parent.mkdir(parents=True, exist_ok=True)
    data = lake_data_path()
    if not data.startswith(("s3://", "gs://", "az://")):
        Path(data).mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(ops), read_only=read_only and ops.exists())
    try:
        configure(con)
        opts = f"DATA_PATH '{data}'" + (", READ_ONLY" if read_only else "")
        con.execute(f"ATTACH IF NOT EXISTS '{lake_uri()}' AS {LAKE} ({opts})")
        con.execute(f"USE {LAKE}")
        if not read_only:
            for s in DATA_SCHEMAS:
                if not con.execute("SELECT 1 FROM information_schema.schemata WHERE catalog_name=? AND schema_name=?",
                                   [LAKE, s]).fetchall():
                    con.execute(f"CREATE SCHEMA {s}")
    except duckdb.Error as e:
        con.close()
        msg = str(e)
        if "extension" in msg.lower() and ("not found" in msg.lower() or "install" in msg.lower()):
            raise WarehouseError("extensão do DuckDB ausente em "
                                 f"{os.environ.get('STACK_DUCKDB_EXTENSIONS')} — reconstrua a imagem (make up): {msg}") from e
        raise
    return con


def lake_snapshot_id(con: duckdb.DuckDBPyConnection) -> int:
    return con.execute(f"SELECT max(snapshot_id) FROM ducklake_snapshots('{LAKE}')").fetchone()[0]


def ops_tables(con: duckdb.DuckDBPyConnection) -> list[str]:
    return [r[0] for r in con.execute("SELECT table_name FROM information_schema.tables WHERE table_catalog='ops' "
                                      "AND table_schema='main' ORDER BY 1").fetchall()]


def reset(con: duckdb.DuckDBPyConnection) -> None:
    """Zera as camadas do lake e o estado operacional (equivale ao `_reset` do gerador compartilhado)."""
    for s in DATA_SCHEMAS:
        con.execute(f"DROP SCHEMA IF EXISTS {LAKE}.{s} CASCADE")
        con.execute(f"CREATE SCHEMA {LAKE}.{s}")
    for t in ops_tables(con):
        con.execute(f"DROP TABLE ops.main.{t}")
