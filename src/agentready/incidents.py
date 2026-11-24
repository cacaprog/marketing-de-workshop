"""Bloco 5: injeção de incidentes "upstream" para a simulação com post-mortem.

O instrutor injeta (de preferência sem dizer qual) e os squads investigam com
`agentready observe`, `agentready lineage` e `agentready trace`.
Cada incidente simula o time de e-commerce reenviando o lote de ONTEM do feed ga4
após um deploy.
"""
from __future__ import annotations

import json
import random
from datetime import datetime

from agentready.db import rows

KINDS = {
    "centavos": "Deploy upstream passou a enviar order_value_brl e discount_brl em CENTAVOS (x100). "
                "Os valores continuam numéricos e >= 0: o contrato aprova. Pilar: Distribuição.",
    "renomeacao": "Deploy upstream renomeou campaign_id -> utm_campaign. Pilar: Esquema "
                  "(o contrato barra o lote; o frescor do ga4 estoura o SLA).",
    "lote_duplicado": "Job upstream reenviou o lote de ontem sem idempotência. Pilar: Volume "
                      "(o contrato barra por chave duplicada; impacto contido).",
    "feed_parado": "Token da integração ga4 expirou; o lote de ontem nunca chegou. Pilar: Frescor.",
}


def _ensure(con) -> None:
    con.execute("""CREATE TABLE IF NOT EXISTS ops.incidents (incident_id VARCHAR, kind VARCHAR, injected_at TIMESTAMP,
        detected_at TIMESTAMP, resolved_at TIMESTAMP, batch_id VARCHAR)""")
    con.execute("CREATE TABLE IF NOT EXISTS meta.incident_backup AS SELECT * FROM bronze.conversions WHERE false")


def _yesterday_ga4(con) -> str:
    return con.execute("""SELECT batch_id FROM bronze.conversions WHERE source='ga4' AND batch_id NOT LIKE '%-retry'
                          ORDER BY ingested_at DESC LIMIT 1""").fetchone()[0]


def inject(con, kind: str | None = None) -> dict:
    _ensure(con)
    if rows(con, "SELECT 1 FROM ops.incidents WHERE resolved_at IS NULL"):
        raise RuntimeError("já existe um incidente aberto — resolva antes de injetar outro")
    kind = kind or random.choice(list(KINDS))
    if kind not in KINDS:
        raise ValueError(f"incidente desconhecido: {kind}. Opções: {list(KINDS)}")
    batch = _yesterday_ga4(con)
    new_batch = f"{batch}-redelivery"
    now = datetime.now()
    con.execute("DELETE FROM meta.incident_backup")
    con.execute("INSERT INTO meta.incident_backup SELECT * FROM bronze.conversions WHERE batch_id = ?", [batch])

    if kind == "centavos":
        con.execute("""UPDATE bronze.conversions SET
            order_value_brl = CAST(round(CAST(order_value_brl AS DOUBLE) * 100) AS BIGINT)::VARCHAR,
            discount_brl = CAST(round(CAST(discount_brl AS DOUBLE) * 100) AS BIGINT)::VARCHAR,
            batch_id = ?, ingested_at = ? WHERE batch_id = ? AND TRY_CAST(order_value_brl AS DOUBLE) IS NOT NULL""",
                    [new_batch, now, batch])
        con.execute("DELETE FROM bronze.conversions WHERE batch_id = ?", [batch])
    elif kind == "renomeacao":
        con.execute("ALTER TABLE bronze.conversions ADD COLUMN IF NOT EXISTS utm_campaign VARCHAR")
        con.execute("""UPDATE bronze.conversions SET utm_campaign = campaign_id, campaign_id = NULL,
                       batch_id = ?, ingested_at = ? WHERE batch_id = ?""", [new_batch, now, batch])
    elif kind == "lote_duplicado":
        con.execute("""INSERT INTO bronze.conversions SELECT * REPLACE (? AS batch_id, ? AS ingested_at)
                       FROM bronze.conversions WHERE batch_id = ?""", [new_batch, now, batch])
    elif kind == "feed_parado":
        con.execute("DELETE FROM bronze.conversions WHERE batch_id = ?", [batch])
        new_batch = batch

    iid = f"INC-{now:%Y%m%d-%H%M%S}"
    con.execute("INSERT INTO ops.incidents VALUES (?,?,?,NULL,NULL,?)", [iid, kind, now, batch])
    return {"incident_id": iid, "injected_at": now.isoformat()}


def open_incident(con) -> dict | None:
    _ensure(con)
    r = rows(con, "SELECT * FROM ops.incidents WHERE resolved_at IS NULL ORDER BY injected_at DESC LIMIT 1")
    return r[0] if r else None


def mark_detected(con) -> dict:
    inc = open_incident(con)
    if not inc:
        raise RuntimeError("nenhum incidente aberto")
    if inc["detected_at"] is None:
        con.execute("UPDATE ops.incidents SET detected_at = ? WHERE incident_id = ?", [datetime.now(), inc["incident_id"]])
    return open_incident(con)


def resolve(con) -> dict:
    """Restaura o lote original (o upstream fez rollback) e fecha o incidente com TTD/TTR."""
    inc = open_incident(con)
    if not inc:
        raise RuntimeError("nenhum incidente aberto")
    now = datetime.now()
    con.execute("DELETE FROM bronze.conversions WHERE batch_id IN (?, ?)", [inc["batch_id"], inc["batch_id"] + "-redelivery"])
    con.execute("ALTER TABLE bronze.conversions DROP COLUMN IF EXISTS utm_campaign")
    con.execute("INSERT INTO bronze.conversions SELECT * FROM meta.incident_backup")
    con.execute("UPDATE ops.incidents SET detected_at = COALESCE(detected_at, ?), resolved_at = ? WHERE incident_id = ?",
                [now, now, inc["incident_id"]])
    return metrics(con, inc["incident_id"])


def metrics(con, incident_id: str) -> dict:
    r = rows(con, "SELECT * FROM ops.incidents WHERE incident_id = ?", [incident_id])[0]
    mins = lambda a, b: round((b - a).total_seconds() / 60, 1) if a and b else None  # noqa: E731
    return {**r, "kind_description": KINDS[r["kind"]], "TTD_min": mins(r["injected_at"], r["detected_at"]),
            "TTR_min": mins(r["injected_at"], r["resolved_at"])}


def reveal(con) -> str:
    inc = open_incident(con) or (rows(con, "SELECT * FROM ops.incidents ORDER BY injected_at DESC LIMIT 1") or [None])[0]
    return json.dumps({**inc, "descricao": KINDS[inc["kind"]]}, default=str, ensure_ascii=False, indent=2) if inc \
        else "nenhum incidente registrado"
