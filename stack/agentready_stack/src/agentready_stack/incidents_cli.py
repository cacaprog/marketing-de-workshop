"""Bloco 5 na trilha stack: ciclo de vida do incidente sobre o warehouse DESTA trilha (pesquisa R8).

Usa as funções compartilhadas de `agentready.incidents` (o registro do incidente, TTD/TTR), que não são
substituídas por nenhuma ferramenta. A diferença para a trilha padrão: `resolve` NÃO chama
`pipeline.run()` — o pipeline da trilha padrão nunca escreve no warehouse da stack. Quem reconstrói as
camadas é o DAG (`make incidente ACAO=resolver` dispara uma execução logo depois).
"""
from __future__ import annotations

from agentready import incidents
from agentready.db import connect, rows


def _say(text: str) -> None:
    print(text, flush=True)


def list_incidents() -> dict:
    con = connect()
    try:
        incidents._ensure(con)
        found = rows(con, "SELECT * FROM ops.incidents ORDER BY injected_at")
    finally:
        con.close()
    if not found:
        _say("Nenhum incidente registrado.")
    for i in found:
        state = "resolvido" if i["resolved_at"] else ("detectado" if i["detected_at"] else "ABERTO")
        _say(f"{i['incident_id']} · injetado {i['injected_at'].isoformat(timespec='seconds')} · {state}")
    if found:
        _say("Decisões do agente desde o último incidente: make decisoes   (ou DESDE=HH:MM, ou DESDE=<horário acima>)")
    return {"incidents": found}


def detect() -> dict:
    con = connect()
    try:
        inc = incidents.mark_detected(con)
    finally:
        con.close()
    _say(f"Detecção registrada para {inc['incident_id']}: {inc['detected_at']} "
         "(o TTD conta da injeção até aqui).")
    return inc


def resolve() -> dict:
    con = connect()
    try:
        m = incidents.resolve(con)
    finally:
        con.close()
    _say(f"Incidente {m['incident_id']} resolvido: o lote original voltou para a Bronze.")
    _say(f"O que aconteceu: {m['kind_description']}")
    _say(f"TTD = {m['TTD_min']} min · TTR = {m['TTR_min']} min")
    _say("As camadas ainda não foram reconstruídas: dispare o DAG (o `make incidente ACAO=resolver` já faz isso).")
    return m


def reveal() -> dict:
    con = connect()
    try:
        text = incidents.reveal(con)
    finally:
        con.close()
    _say(text)
    return {"reveal": text}


ACTIONS = {"list": list_incidents, "detect": detect, "resolve": resolve, "reveal": reveal}


def decisions_since(since: str) -> dict:
    """FR-012: decisões do agente desde T — alterações executadas e pedidos na fila — com o trace_id e o
    link da tarefa do agente no Marquez. Consulta própria da stack (substitui
    observability.decisions_since(), que pertence ao módulo substituído)."""
    from agentready_stack import lineage
    con = connect()
    try:
        ts = parse_since(con, since)
        found = rows(con, """
            SELECT change_id AS id, campaign_id, action, old_value || ' -> ' || new_value AS change, trace_id,
                   changed_at AS ts, 'executada' AS kind
            FROM ops.change_log WHERE changed_at >= ?
            UNION ALL
            SELECT request_id, json_extract_string(params, '$.campaign_id'), action,
                   json_extract_string(params, '$.new_daily_budget_brl'), trace_id, requested_at, 'na fila'
            FROM ops.approval_queue WHERE requested_at >= ?
            ORDER BY ts""", [ts, ts])
    finally:
        con.close()
    _say(f"Decisões do agente desde {ts.isoformat(sep=' ', timespec='seconds')} (candidatas a rollback):")
    if not found:
        _say("  nenhuma")
    from agentready_stack import telemetry
    for d in found:
        d["trace_url"] = telemetry.trace_url(d["trace_id"])
        _say(f"  {d['ts']} · {d['kind']} · {d['id']} · {d['campaign_id']} · {d['action']} · {d['change']} "
             f"· trace {d['trace_url'] or d['trace_id']}")
    _say(f"Linhagem da tarefa do agente (Marquez): {lineage.agent_job_link()}")
    return {"since": ts.isoformat(), "decisions": found, "lineage_link": lineage.agent_job_link()}


def parse_since(con, since: str | None):
    """Horário de início para `decisoes`, do jeito que se digita no palco:
    vazio ou 'incidente' → injeção do último incidente; 'HH:MM[:SS]' → hoje; ISO com espaço ou 'T'."""
    from datetime import date, datetime, time
    text = (since or "").strip()
    if text in ("", "incidente"):
        incidents._ensure(con)
        r = rows(con, "SELECT injected_at FROM ops.incidents ORDER BY injected_at DESC LIMIT 1")
        if not r:
            raise ValueError("nenhum incidente registrado: informe DESDE=AAAA-MM-DDTHH:MM ou DESDE=HH:MM")
        return r[0]["injected_at"]
    try:
        return datetime.combine(date.today(), time.fromisoformat(text)) if ":" in text and "-" not in text \
            else datetime.fromisoformat(text)
    except ValueError:
        raise ValueError(f"horário inválido: '{text}'. Use HH:MM, AAAA-MM-DDTHH:MM ou deixe vazio "
                         "(= desde o último incidente)") from None


def traces(limit: int = 10) -> dict:
    """Fase 3 (`make traces`): últimas execuções do agente com o link do trace no Phoenix.

    A coluna incidente mostra o incidente ABERTO na hora da execução pelo id, nunca pelo tipo (no modo
    aleatório do Bloco 5 os squads não podem ver o tipo)."""
    from agentready_stack import ledger, telemetry
    con = connect()
    try:
        ledger.ensure(con)
        has_incidents = bool(rows(con, "SELECT 1 FROM information_schema.tables "
                                       "WHERE table_schema='ops' AND table_name='incidents'"))
        incident = ("""(SELECT max(i.incident_id) FROM ops.incidents i WHERE i.injected_at <= r.started_at
                         AND (i.resolved_at IS NULL OR i.resolved_at > r.started_at))""" if has_incidents else "NULL")
        runs = rows(con, f"""SELECT r.dag_run_id, CAST(r.business_date AS VARCHAR) AS business_date, r.status,
                                    r.trace_id, r.started_at, {incident} AS incident
                             FROM ops.agent_runs r ORDER BY r.started_at DESC LIMIT ?""", [limit])
    finally:
        con.close()
    _say("execução · data de negócio · incidente · agente · link")
    if not runs:
        _say("  nenhuma execução do agente ainda (make run)")
    for r in runs:
        r["trace_url"] = telemetry.trace_url(r["trace_id"])
        link = r["trace_url"] or ("— sem trace (pulado: já decidido para estes dados)" if r["status"] == "skipped_duplicate"
                                  else "— sem trace")
        _say(f"  {r['dag_run_id'] or '(manual)'} · {r['business_date']} · {r['incident'] or 'nenhum'} · {r['status']} · {link}")
    return {"runs": runs}
