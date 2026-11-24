"""Livro-razão das execuções do agente (ops.agent_runs): idempotência e retentativa segura.

Regras (pesquisa R8):
  * Mesma impressão digital já concluída  -> o agente NÃO roda de novo (skipped_duplicate).
  * Execução anterior inacabada que JÁ aplicou mudanças -> failed_partial; um humano resolve.
  * Execução anterior inacabada sem mudanças -> marcada failed; roda de novo normalmente.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime

from agentready.db import rows
from agentready.settings import model_version_info

STATUSES = ("running", "done", "skipped_duplicate", "failed", "failed_partial")


def ensure(con) -> None:
    con.execute("""CREATE TABLE IF NOT EXISTS ops.agent_runs (run_id VARCHAR, dag_run_id VARCHAR,
        business_date DATE, input_fingerprint VARCHAR, status VARCHAR, trace_id VARCHAR,
        started_at TIMESTAMP, finished_at TIMESTAMP, report JSON)""")


def effective_override(con) -> str:
    con.execute("CREATE TABLE IF NOT EXISTS ops.autonomy_override (level VARCHAR)")
    r = con.execute("SELECT level FROM ops.autonomy_override").fetchone()
    return r[0] if r else "none"


def fingerprint(con, brain: str, gullible: bool) -> str:
    """O que a decisão do agente depende: Gold, estado das fontes, data, versões e ajustes da execução.

    age_hours fica de fora de propósito: muda a cada minuto. O que importa para decidir é o status
    (fresh/stale) de cada fonte, e esse sim entra.

    Valores em R$ entram arredondados a centavos: o DuckDB soma em paralelo, e a ordem da soma muda
    os últimos dígitos do ponto flutuante a cada rebuild (34056.33 vs 34056.330000000005). Sem o
    arredondamento, uma reexecução idêntica parecia "nova" e o agente decidia de novo.
    """
    h = hashlib.sha256()
    for sql in ("SELECT day, campaign_id, campaign_name, channel, objective, conversion_source, impressions, clicks, "
                "round(spend_brl, 2), orders, round(gross_revenue_brl, 2), round(discount_brl, 2) "
                "FROM gold.campaign_daily ORDER BY ALL",
                "SELECT dataset, \"partition\", last_success_ingest, sla_hours, status FROM gold.source_health ORDER BY ALL"):
        h.update(repr(con.execute(sql).fetchall()).encode())
    today = con.execute("SELECT current_date").fetchone()[0]
    h.update(json.dumps({"date": str(today), "versions": model_version_info(), "override": effective_override(con),
                         "brain": brain, "gullible": bool(gullible)}, sort_keys=True).encode())
    return h.hexdigest()


def already_done(con, fp: str) -> bool:
    ensure(con)
    return bool(con.execute("SELECT 1 FROM ops.agent_runs WHERE input_fingerprint=? AND status='done'", [fp]).fetchone())


@dataclass
class Unfinished:
    run_id: str
    started_at: datetime
    changes: list[dict] = field(default_factory=list)
    requests: list[dict] = field(default_factory=list)

    @property
    def applied_something(self) -> bool:
        return bool(self.changes or self.requests)


def prior_unfinished(con, fp: str) -> Unfinished | None:
    ensure(con)
    r = rows(con, """SELECT run_id, started_at FROM ops.agent_runs WHERE input_fingerprint=?
                     AND status IN ('running','failed') ORDER BY started_at DESC LIMIT 1""", [fp])
    if not r:
        return None
    u = Unfinished(r[0]["run_id"], r[0]["started_at"])
    u.changes = rows(con, """SELECT change_id, campaign_id, action, field, old_value, new_value, actor, changed_at
                             FROM ops.change_log WHERE actor LIKE 'agent%' AND changed_at >= ? ORDER BY changed_at""",
                     [u.started_at])
    u.requests = rows(con, """SELECT request_id, action, status, requested_at FROM ops.approval_queue
                              WHERE requested_by='agent' AND requested_at >= ? ORDER BY requested_at""", [u.started_at])
    return u


def start(con, fp: str, dag_run_id: str | None) -> str:
    ensure(con)
    run_id = "RUN-" + uuid.uuid4().hex[:8]
    con.execute("INSERT INTO ops.agent_runs VALUES (?,?,current_date,?,'running',NULL,?,NULL,NULL)",
                [run_id, dag_run_id, fp, datetime.now()])
    return run_id


def record(con, fp: str, dag_run_id: str | None, status: str) -> str:
    """Registra uma execução que terminou sem rodar o agente (ex.: skipped_duplicate)."""
    assert status in STATUSES
    run_id = start(con, fp, dag_run_id)
    finish(con, run_id, status)
    return run_id


def finish(con, run_id: str, status: str, trace_id: str | None = None, report: dict | None = None) -> None:
    assert status in STATUSES
    con.execute("UPDATE ops.agent_runs SET status=?, trace_id=?, finished_at=?, report=? WHERE run_id=?",
                [status, trace_id, datetime.now(), json.dumps(report, ensure_ascii=False, default=str) if report else None,
                 run_id])
