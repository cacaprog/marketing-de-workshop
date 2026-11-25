"""Ponte entre os contratos ODCS e os modelos Python do dbt (roda no venv do dbt).

Fica FORA de stack/dbt/aurora/models/ de propósito: o dbt trata todo .py de models/ como
modelo, e modelos Python não importam arquivos vizinhos. Importa só agentready.contracts,
agentready.pipeline e duckdb (o venv do dbt não tem Airflow, mcp nem OpenTelemetry).

As regras continuam em um único lugar: agentready.contracts.violation_exprs() (pesquisa R5).
"""
from __future__ import annotations

import math
from datetime import datetime

from agentready import contracts

CONTRACT_NAMES = ("campaigns", "ad_spend", "conversions")


def _lit(v) -> str:
    """Literal SQL seguro para valores simples (texto, número, data/hora, None)."""
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, (int, float)):
        if isinstance(v, float) and math.isinf(v):
            return "'inf'::DOUBLE"
        return repr(v)
    if isinstance(v, datetime):
        return f"TIMESTAMP '{v.isoformat(sep=' ')}'"
    return "'" + str(v).replace("'", "''") + "'"


def values_relation(session, rows: list[dict], columns: dict[str, str]):
    """Relação DuckDB a partir de linhas Python, com tipos explícitos (sem pandas/pyarrow)."""
    cols = ", ".join(f'CAST(NULL AS {t}) AS "{c}"' for c, t in columns.items())
    if not rows:
        return session.sql(f"SELECT {cols} WHERE FALSE")
    selects = [
        "SELECT " + ", ".join(f'CAST({_lit(r.get(c))} AS {t}) AS "{c}"' for c, t in columns.items())
        for r in rows
    ]
    return session.sql(" UNION ALL ".join(selects))


def silver_select(c: contracts.Contract) -> str:
    """Lista de colunas tipadas da Silver (mesmo mapeamento CASTS do contracts.apply)."""
    return ", ".join(
        f"CAST({p['name']} AS {contracts.CASTS[p.get('logicalType', 'string')]}) AS {p['name']}"
        if p.get("logicalType") in contracts.CASTS and p["name"] != "ingested_at" else p["name"]
        for p in c.properties)


def quarantine_payload(c: contracts.Contract) -> str:
    return "to_json(struct_pack(" + ", ".join(f"{col} := {col}" for col in c.columns) + "))"


def registry_rows(session) -> list[dict]:
    out = []
    for c in contracts.load_all():
        out.append({
            "contract": c.name, "contract_version": c.version, "table_name": c.table,
            "max_quarantine_rate": c.max_quarantine_rate, "sla_hours": c.freshness_hours,
            "partition_by": c.freshness_partition,
            "missing_columns": contracts.missing_columns(session, c),
            "silver_select": silver_select(c), "quarantine_payload": quarantine_payload(c),
            # Fase 2: o pilar de esquema (obs_esquema) compara a tabela física com estas colunas.
            "physical": c.physical, "columns": list(c.columns),
            "required_columns": [p["name"] for p in c.properties if p.get("required")],
        })
    return out


def registry_relation(session):
    rows = registry_rows(session)
    cols = {"contract": "VARCHAR", "contract_version": "VARCHAR", "table_name": "VARCHAR",
            "max_quarantine_rate": "DOUBLE", "sla_hours": "DOUBLE", "partition_by": "VARCHAR",
            "silver_select": "VARCHAR", "quarantine_payload": "VARCHAR", "physical": "VARCHAR"}
    base = values_relation(session, rows, cols)
    # As listas são montadas à parte para não depender de literais de lista no helper.
    lst = lambda xs: "[" + ", ".join(_lit(x) for x in xs) + "]::VARCHAR[]"  # noqa: E731
    lists = " UNION ALL ".join(
        f"SELECT {_lit(r['contract'])} AS contract, {lst(r['missing_columns'])} AS missing_columns, "
        f"{lst(r['columns'])} AS columns, {lst(r['required_columns'])} AS required_columns"
        for r in rows)
    return session.sql(f"SELECT b.*, m.missing_columns, m.columns, m.required_columns "
                       f"FROM ({base.sql_query()}) b JOIN ({lists}) m USING (contract)")


def checked_relation(session, name: str):
    """Cada linha da Bronze + a lista de violações do contrato (vazia = linha válida).

    Quebra de esquema (coluna do contrato ausente na Bronze): todas as linhas recebem a
    violação 'esquema: colunas ausentes', então todo lote sai barrado com taxa 1,0 — igual a
    contracts._record_batches(schema_break=True). Silver e Quarentena mantêm o conteúdo anterior.
    """
    c = contracts.load(name)
    missing = contracts.missing_columns(session, c)
    if missing:
        cols = ", ".join("ingested_at" if col == "ingested_at" else f"CAST(NULL AS VARCHAR) AS {col}"
                         for col in c.columns)
        reason = _lit("esquema: colunas ausentes: " + ", ".join(missing))
        return session.sql(f"SELECT {cols}, batch_id, [{reason}] AS violations FROM {c.physical}")
    viol = ", ".join(contracts.violation_exprs(c))
    cols = ", ".join(c.columns)
    return session.sql(f"SELECT {cols}, batch_id, list_filter([{viol}], lambda x: x IS NOT NULL) AS violations "
                       f"FROM {c.physical} b")
