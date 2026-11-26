"""Fase 3 (FR-008): rollback ligado à decisão original.

Envolve o rollback COMPARTILHADO (capabilities.rollback, o mesmo do `agentready rollback`) num span da
stack, `humano.rollback`, com um span link para o `agent.run` que tomou a decisão e o link do Phoenix.
O span `human.rollback` do código compartilhado nasce filho dele e vai para o log de auditoria, como
sempre. O rollback acontece fora da execução do DAG: é um trace próprio, LIGADO (não aninhado) ao original.
"""
from __future__ import annotations

from agentready import capabilities as cap
from agentready import tracing
from agentready_stack.warehouse import connect

from agentready_stack import parity, telemetry


def _agent_span_id(trace_id: str | None) -> str | None:
    """O agent.run da decisão. Com retentativa há mais de um no trace: vale o último (o da tentativa que terminou)."""
    if not trace_id:
        return None
    roots = [r for r in tracing.load(trace_id) if r["name"] == "agent.run"]
    return parity.latest_agent_run(roots)["span_id"] if roots else None


def run(change_id: str, actor: str = "instrutor") -> dict:
    con = connect()
    try:
        row = con.execute("SELECT trace_id, rolled_back FROM ops.change_log WHERE change_id=?", [change_id]).fetchone()
        if row is None:
            raise ValueError(f"alteração {change_id} não encontrada em ops.change_log")
        if row[1]:
            # nada a desfazer: não registrar um humano.rollback que não aconteceu
            raise ValueError(f"alteração {change_id} já foi revertida")
        trace_id = row[0]
        url = telemetry.trace_url(trace_id)
        span_id = _agent_span_id(trace_id)
        links = [telemetry.link_to(trace_id, span_id)] if span_id else None
        with telemetry.span("humano.rollback", links=links, **{"change_id": change_id, "actor": actor,
                                                               "agentready.original_trace_id": trace_id,
                                                               "agentready.original_trace_url": url}) as sp:
            message = cap.rollback(con, change_id, actor)
            telemetry.set_attrs(sp, **{"agentready.message": str(message)})
    finally:
        con.close()
    print(message, flush=True)
    print(f"Decisão original: {url or 'sem trace registrado para esta alteração'}", flush=True)
    return {"change_id": change_id, "message": str(message), "original_trace_url": url}
