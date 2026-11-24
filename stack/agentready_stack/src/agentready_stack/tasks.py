"""Tarefas do DAG aurora_midia_diario (rodam no venv do agente, via `agentready-stack task ...`).

Cada função recebe parâmetros simples, escreve um relato em pt-BR (log da tarefa) e devolve um
dicionário que vira XCom. O agente, as capacidades e a camada semântica são os da trilha padrão.
"""
from __future__ import annotations

import json
from datetime import datetime

from agentready import autonomy, generate, incidents
from agentready.agent import ReadyAgent
from agentready.db import connect, rows

from agentready_stack import approvals, ledger

KINDS = ("nenhum", "centavos", "renomeacao", "lote_duplicado", "feed_parado", "aleatorio")
OVERRIDES = ("manter", "shadow", "supervised", "guarded", "full", "limpar")


class PartialApplyError(RuntimeError):
    """Retentativa encontrou mudanças já aplicadas por uma execução inacabada: um humano decide."""


class QualityAlert(RuntimeError):
    """Lotes NOVOS barrados (disjuntor ou quebra de esquema): a execução fica marcada para atenção."""


def say(text: str) -> None:
    print(text, flush=True)


def _bronze_ready(con) -> bool:
    return bool(con.execute("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='bronze' "
                            "AND table_name='conversions'").fetchone()[0])


def ingest(params: dict) -> dict:
    """Etapa 1. Na Fase 1 não há upstream ao vivo: a 'ingestão' aplica os parâmetros da execução."""
    p = {"reset_scenario": False, "backfill_meta": False, "incident": "nenhum", "autonomy_override": "manter"} | params
    if p["incident"] not in KINDS:
        raise ValueError(f"incidente inválido: {p['incident']}. Use {KINDS}")
    if p["autonomy_override"] not in OVERRIDES:
        raise ValueError(f"autonomia inválida: {p['autonomy_override']}. Use {OVERRIDES}")
    applied = []
    con = connect()
    try:
        if p["reset_scenario"] or not _bronze_ready(con):
            con.close()
            stats = generate.generate()
            con = connect()
            applied.append(f"cenário gerado ({stats['ad_spend_rows']} linhas de investimento, "
                           f"{stats['conversion_rows']} conversões)"
                           + ("" if p["reset_scenario"] else " — primeira execução, Bronze estava vazia"))
        if p["backfill_meta"]:
            n = generate.backfill_meta(con)
            applied.append(f"backfill da Meta: {n} conversões atrasadas chegaram")
        if p["incident"] != "nenhum":
            r = incidents.inject(con, None if p["incident"] == "aleatorio" else p["incident"])
            # Tipo não é revelado no modo aleatório (os squads investigam, como na trilha padrão).
            applied.append(f"incidente injetado: {r['incident_id']}"
                           + ("" if p["incident"] == "aleatorio" else f" ({p['incident']})"))
        if p["autonomy_override"] != "manter":
            level = None if p["autonomy_override"] == "limpar" else p["autonomy_override"]
            autonomy.set_override(con, level)
            applied.append(f"autonomia global: {level or 'sem override'}")
    finally:
        con.close()
    reference_ts = datetime.now().replace(microsecond=0).isoformat()
    say("Ingestão: " + ("; ".join(applied) if applied else "nada a aplicar (sem upstream ao vivo na Fase 1)"))
    say(f"Horário de referência desta execução (frescor/SLA): {reference_ts}")
    return {"reference_ts": reference_ts, "applied": applied}


def run_agent(brain: str = "rules", gullible: bool = False, dag_run_id: str | None = None) -> dict:
    """Etapa 5. Livro-razão (idempotência) -> agente da trilha padrão -> pedidos de aprovação."""
    con = connect()
    try:
        fp = ledger.fingerprint(con, brain, gullible)
        if ledger.already_done(con, fp):
            ledger.record(con, fp, dag_run_id, "skipped_duplicate")
            say("Agente NÃO executado: já decidido para estes dados (mesma Gold, mesmas fontes, mesmos ajustes).")
            return {"status": "skipped_duplicate", "trace_id": None, "steps": [], "requests": [], "hitl": []}
        prior = ledger.prior_unfinished(con, fp)
        if prior is not None:
            if prior.applied_something:
                ledger.finish(con, prior.run_id, "failed_partial")
                say(f"ATENÇÃO: a execução anterior {prior.run_id} aplicou {len(prior.changes)} alteração(ões) e "
                    f"{len(prior.requests)} pedido(s) e falhou. O agente NÃO vai rodar de novo.")
                for ch in prior.changes:
                    say(f"  {ch['change_id']} · {ch['campaign_id']} · {ch['field']}: {ch['old_value']} -> "
                        f"{ch['new_value']} ({ch['actor']})")
                for rq in prior.requests:
                    say(f"  {rq['request_id']} · {rq['action']} · {rq['status']}")
                say("Revise, use `agentready rollback <CHG>` se necessário e marque como resolvida.")
                raise PartialApplyError(f"execução anterior {prior.run_id} aplicou mudanças e falhou")
            ledger.finish(con, prior.run_id, "failed")
        run_id = ledger.start(con, fp, dag_run_id)
        try:
            rep = ReadyAgent(brain, gullible).run(con)
        except Exception:
            ledger.finish(con, run_id, "failed")
            raise
        say(f"== {rep.agent} · trace {rep.trace_id}")
        for s in rep.steps:
            say(f"[{s.kind}] {s.text}")
        results = {s.data["result"]["request_id"]: s.data["result"] for s in rep.steps
                   if s.kind == "action" and (s.data.get("result") or {}).get("request_id")}
        pend = rows(con, "SELECT request_id FROM ops.approval_queue WHERE status='pending' AND trace_id=? "
                         "ORDER BY requested_at", [rep.trace_id])
        details = [approvals.request_details(con, r["request_id"], results.get(r["request_id"])) for r in pend]
        steps = [{"kind": s.kind, "text": s.text} for s in rep.steps]
        ledger.finish(con, run_id, "done", rep.trace_id, {"steps": steps, "requests": [d["request_id"] for d in details]})
        if details:
            say(f"{len(details)} ação(ões) aguardando aprovação humana: " + ", ".join(d["request_id"] for d in details))
        return {"status": "done", "trace_id": rep.trace_id, "steps": steps, "requests": details,
                "hitl": [approvals.to_hitl_kwargs(d) for d in details]}
    finally:
        con.close()


def apply_decision(request_id: str, payload: dict | None, timeout_at: str | None = None) -> dict:
    """Etapa 7. Aplica a decisão do HITL pelo caminho da trilha padrão (reverifica o estado vivo)."""
    con = connect()
    try:
        res = approvals.apply(con, request_id, payload, datetime.fromisoformat(timeout_at) if timeout_at else None)
    finally:
        con.close()
    say(f"{request_id}: {res['outcome']}" + (f" por {res['decided_by']}" if res.get("decided_by") else "")
        + (f" — {res['message']}" if res.get("message") else ""))
    return res


def quality_alert() -> dict:
    """Etapa 3a (folha). Falha só com lotes barrados NOVOS — carregados depois da marca d'água da
    última execução bem-sucedida (pesquisa R7). O lote antigo barrado para sempre não acende o alerta."""
    con = connect()
    try:
        con.execute("""CREATE TABLE IF NOT EXISTS ops.stack_watermark (last_success_ingest_max TIMESTAMP,
                       dag_run_id VARCHAR, updated_at TIMESTAMP)""")
        wm = con.execute("SELECT max(last_success_ingest_max) FROM ops.stack_watermark").fetchone()[0]
        new = rows(con, """SELECT b.contract, b.batch_id, b.ingested_at, round(b.rate * 100, 1) AS pct,
                                  round(r.max_quarantine_rate * 100) AS limit_pct
                           FROM meta.batch_status b JOIN meta.contract_registry r USING (contract)
                           WHERE b.status = 'barred' AND (? IS NULL OR b.ingested_at > ?)
                           ORDER BY b.ingested_at""", [wm, wm])
    finally:
        con.close()
    if not new:
        say("Qualidade: nenhum lote novo barrado desde a última execução bem-sucedida"
            + (f" (marca d'água {wm})." if wm else "."))
        return {"new_barred": [], "watermark": str(wm) if wm else None}
    say(f"ATENÇÃO — {len(new)} lote(s) NOVO(S) barrado(s) pelo contrato (o agente só vê o último dado bom):")
    say("contrato | lote | carregado em | quarentena | limite")
    for r in new:
        say(f"{r['contract']} | {r['batch_id']} | {r['ingested_at']} | {r['pct']}% | {r['limit_pct']:.0f}%")
    raise QualityAlert("lotes novos barrados: " + ", ".join(r["batch_id"] for r in new))


def close_run(dag_run_id: str | None = None) -> dict:
    """Etapa 8. Atualiza a marca d'água (base do alerta 'só problemas novos') e resume a execução."""
    con = connect()
    try:
        con.execute("""CREATE TABLE IF NOT EXISTS ops.stack_watermark (last_success_ingest_max TIMESTAMP,
                       dag_run_id VARCHAR, updated_at TIMESTAMP)""")
        wm = con.execute("""SELECT max(m) FROM (SELECT max(ingested_at) m FROM silver.campaigns UNION ALL
                            SELECT max(ingested_at) FROM silver.ad_spend UNION ALL
                            SELECT max(ingested_at) FROM silver.conversions)""").fetchone()[0]
        con.execute("DELETE FROM ops.stack_watermark")
        con.execute("INSERT INTO ops.stack_watermark VALUES (?,?,?)", [wm, dag_run_id, datetime.now()])
        stale = [f"{r['dataset']}/{r['partition']}" for r in
                 rows(con, "SELECT dataset, \"partition\" FROM gold.source_health WHERE status='stale'")]
        pend = con.execute("SELECT COUNT(*) FROM ops.approval_queue WHERE status='pending'").fetchone()[0]
    finally:
        con.close()
    summary = (f"Execução concluída. Marca d'água: {wm}. Fontes fora do SLA: {', '.join(stale) or 'nenhuma'}. "
               f"Pedidos ainda pendentes: {pend}.")
    say(summary)
    return {"watermark": str(wm), "stale_sources": stale, "pending_requests": pend, "summary": summary}


def dumps(result: dict) -> str:
    return json.dumps(result, ensure_ascii=False, default=str)
