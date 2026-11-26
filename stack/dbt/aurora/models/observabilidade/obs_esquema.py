"""Pilar ESQUEMA (Fase 2): mesma regra de observability.schema() — por contrato, colunas a mais ou a
menos na tabela física da Bronze e colunas obrigatórias mais de 50% nulas no último lote.

Modelo Python porque a checagem de nulos monta uma consulta por coluna obrigatória. As colunas vêm de
meta.contract_registry (publicado a partir dos arquivos ODCS), não de uma cópia dos contratos.
"""


def _cursor(session):
    """Sub-cursor no MESMO catálogo da sessão (Fase 4: o lake `warehouse`). Um cursor novo começa no arquivo
    principal da conexão (ops.duckdb) e não passa pelo plugin do dbt."""
    cur = session.cursor()
    cur.execute(f"USE {session.sql('SELECT current_database()').fetchall()[0][0]}")
    return cur


def model(dbt, session):
    dbt.config(materialized="table")
    registry = dbt.ref("contract_registry")
    dbt.source("bronze", "campaigns")
    dbt.source("bronze", "ad_spend")
    dbt.source("bronze", "conversions")
    contracts = session.sql(
        f"SELECT contract, contract_version, physical, columns, required_columns FROM ({registry.sql_query()}) "
        "ORDER BY contract").fetchall()
    out = []
    for _name, version, physical, columns, required in contracts:
        schema, table = physical.split(".")
        present = {r[0] for r in _cursor(session).execute(
            "SELECT column_name FROM information_schema.columns WHERE table_catalog = current_database() "
            "AND table_schema=? AND table_name=?",
            [schema, table]).fetchall()}
        expected = set(columns) | {"batch_id"}
        extra, missing = sorted(present - expected), sorted(expected - present)
        nulls = []
        for col in required:
            if col not in present:
                continue
            n = _cursor(session).execute(f"""SELECT COUNT(*) FILTER (WHERE {col} IS NULL) / COUNT(*) FROM {physical}
                                    WHERE batch_id = (SELECT batch_id FROM {physical} ORDER BY ingested_at DESC LIMIT 1)
                                 """).fetchone()[0]
            if n and n > 0.5:
                nulls.append(f"{col} {n:.0%} nulo no último lote")
        ok = not (extra or missing or nulls)
        detail = ("conforme contrato v" + version if ok else
                  "; ".join(filter(None, [extra and f"colunas inesperadas {extra}",
                                          missing and f"colunas ausentes {missing}", *nulls])))
        out.append((physical, "pass" if ok else "fail", detail))
    values = ", ".join("(" + ", ".join("'" + str(v).replace("'", "''") + "'" for v in row) + ")" for row in out)
    return session.sql(f"""
        SELECT 'esquema' AS pillar, target, status, CAST(NULL AS DOUBLE) AS observed,
               CAST(NULL AS DOUBLE) AS baseline, CAST(NULL AS DOUBLE) AS ratio, detail
        FROM (VALUES {values}) v(target, status, detail)""")
