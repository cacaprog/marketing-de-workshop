"""Fase 4 — plugin do dbt-duckdb: todo cursor do dbt começa no lake (`USE warehouse`).

Os modelos Python rodam código compartilhado (pipeline.freshness, contracts.missing_columns) com nomes sem catálogo
(`bronze.conversions`, `silver.campaigns`). Na stack esses nomes vivem no DuckLake anexado como `warehouse`; o arquivo
principal da conexão é o ops.duckdb. Este plugin faz cada cursor resolver como a conexão da stack (warehouse.py).
"""
from __future__ import annotations

from dbt.adapters.duckdb.plugins import BasePlugin

from agentready_stack.warehouse import LAKE


class Plugin(BasePlugin):
    # Só o cursor: `configure_connection` roda antes do ATTACH do lake (o catálogo ainda não existe).
    def configure_cursor(self, cursor) -> None:
        cursor.execute(f"USE {LAKE}")
