"""Fase 4 — snapshots do lake com nome: marcos (checkpoints) por etapa da execução.

O DuckLake cria um snapshot a cada commit (cada carga, cada modelo dbt). Os marcos dão nome a eles — "antes de o
agente decidir na terça" — e ficam no ops.duckdb, para uma restauração nunca apagar o próprio índice.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from agentready_stack import warehouse

FONTES = ("ads", "ga4", "meta_capi", "catalogo")
ETAPAS = ("reset", *(f"ingestao.{f}" for f in FONTES), "contratos", "gold_observabilidade", "agente", "restauracao")


def ensure(con) -> None:
    con.execute("""CREATE TABLE IF NOT EXISTS ops.lake_checkpoints (checkpoint_id VARCHAR, dag_run_id VARCHAR,
        etapa VARCHAR, snapshot_id BIGINT, incident_id VARCHAR, lotes VARCHAR[], criado_em TIMESTAMP)""")


def open_incident_id(con) -> str | None:
    """O incidente aberto agora, sem criar nada (o `incidents._ensure` compartilhado cria tabelas no lake)."""
    if not con.execute("SELECT 1 FROM information_schema.tables WHERE table_catalog='ops' AND table_name='incidents'"
                       ).fetchall():
        return None
    r = con.execute("SELECT incident_id FROM ops.incidents WHERE resolved_at IS NULL ORDER BY injected_at DESC LIMIT 1"
                    ).fetchall()
    return r[0][0] if r else None


def checkpoint(con, etapa: str, dag_run_id: str | None = None, lotes: list[str] | None = None) -> str:
    if etapa not in ETAPAS:
        raise ValueError(f"etapa inválida para um marco do lake: {etapa}. Use {ETAPAS}")
    ensure(con)
    ck = "CK-" + uuid.uuid4().hex[:8]
    con.execute("INSERT INTO ops.lake_checkpoints VALUES (?,?,?,?,?,?,?)",
                [ck, dag_run_id, etapa, warehouse.lake_snapshot_id(con), open_incident_id(con),
                 list(lotes) if lotes else None, datetime.now()])
    return ck
