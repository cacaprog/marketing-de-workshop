"""Tarefas do DAG aurora_midia_diario (rodam no venv do agente, via `agentready-stack task ...`).

Cada função recebe parâmetros simples, escreve um relato em pt-BR (log da tarefa) e devolve um
dicionário que vira XCom. O agente, as capacidades e a camada semântica são os da trilha padrão.
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

import yaml

from agentready import autonomy, generate, incidents
from agentready.settings import guardrails
from agentready.agent import ReadyAgent
from agentready.db import connect, rows

from agentready_stack import approvals, ledger

KINDS = ("nenhum", "centavos", "renomeacao", "lote_duplicado", "feed_parado", "aleatorio")
OVERRIDES = ("manter", "shadow", "supervised", "guarded", "full", "limpar")
BREAKERS = ("compartilhado", "ligado", "desligado")
OBS_DEFAULTS = {"bands": {"volume": [0.5, 1.5], "distribution": [0.5, 2.0]}, "min_history": 7}


def stack_config() -> dict:
    """stack/config/stack.yaml (no container: STACK_CONFIG). Nos testes locais, o arquivo do repositório."""
    for path in (os.environ.get("STACK_CONFIG"), Path(__file__).resolve().parents[3] / "config" / "stack.yaml"):
        if path and Path(path).exists():
            return yaml.safe_load(Path(path).read_text()) or {}
    return {}


def observability_settings() -> dict:
    obs = stack_config().get("observability") or {}
    return {"bands": obs.get("bands") or OBS_DEFAULTS["bands"],
            "min_history": int(obs.get("min_history", OBS_DEFAULTS["min_history"]))}


def resolve_breaker(choice: str) -> dict:
    """Disjuntor de distribuição desta execução (FR-005): a configuração compartilhada, ou o override."""
    if choice not in BREAKERS:
        raise ValueError(f"disjuntor_distribuicao inválido: {choice}. Use {BREAKERS}")
    if choice == "compartilhado":
        return {"value": bool(guardrails()["observability"]["block_on_distribution_anomaly"]), "source": "compartilhado"}
    return {"value": choice == "ligado", "source": "override"}


class PartialApplyError(RuntimeError):
    """Retentativa encontrou mudanças já aplicadas por uma execução inacabada: um humano decide."""


class QualityAlert(RuntimeError):
    """Lotes NOVOS barrados (disjuntor ou quebra de esquema): a execução fica marcada para atenção."""


def say(text: str) -> None:
    print(text, flush=True)


def _bronze_ready(con) -> bool:
    return bool(con.execute("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='bronze' "
                            "AND table_name='conversions'").fetchone()[0])


def ingest(params: dict, dag_run_id: str | None = None) -> dict:
    """Etapa 1. Não há upstream ao vivo (até a Fase 4): a 'ingestão' aplica os parâmetros da execução
    e decide o disjuntor de distribuição desta execução (Fase 2)."""
    p = {"reset_scenario": False, "backfill_meta": False, "incident": "nenhum", "autonomy_override": "manter",
         "disjuntor_distribuicao": "compartilhado"} | params
    breaker = resolve_breaker(p["disjuntor_distribuicao"])
    obs = observability_settings()
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
        con.execute("""CREATE TABLE IF NOT EXISTS ops.stack_run_settings (dag_run_id VARCHAR,
                       block_on_distribution_anomaly BOOLEAN, source VARCHAR, min_history INTEGER, decided_at TIMESTAMP)""")
        con.execute("INSERT INTO ops.stack_run_settings VALUES (?,?,?,?,?)",
                    [dag_run_id, breaker["value"], breaker["source"], obs["min_history"], datetime.now()])
    finally:
        con.close()
    reference_ts = datetime.now().replace(microsecond=0).isoformat()
    say("Ingestão: " + ("; ".join(applied) if applied else "nada a aplicar (sem upstream ao vivo até a Fase 4)"))
    say(f"Horário de referência desta execução (frescor/SLA): {reference_ts}")
    say(f"Disjuntor de distribuição: {'ligado' if breaker['value'] else 'desligado'} ("
        + ("configuração compartilhada, config/guardrails.yaml" if breaker["source"] == "compartilhado"
           else "override desta execução") + ")")
    return {"reference_ts": reference_ts, "applied": applied, "breaker": breaker,
            "min_history": obs["min_history"], "obs_bands": obs["bands"]}


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
                                  round(r.max_quarantine_rate * 100) AS limit_pct, b.barred_by
                           FROM meta.batch_status b JOIN meta.contract_registry r USING (contract)
                           WHERE b.status = 'barred' AND (? IS NULL OR b.ingested_at > ?)
                           ORDER BY b.ingested_at""", [wm, wm])
    finally:
        con.close()
    if not new:
        say("Qualidade: nenhum lote novo barrado desde a última execução bem-sucedida"
            + (f" (marca d'água {wm})." if wm else "."))
        return {"new_barred": [], "watermark": str(wm) if wm else None}
    say(f"ATENÇÃO — {len(new)} lote(s) NOVO(S) barrado(s) (o agente só vê o último dado bom):")
    say("contrato | lote | carregado em | motivo")
    for r in new:
        why = ("barrado por anomalia de distribuição (ticket médio fora da faixa)" if r["barred_by"] == "distribuicao"
               else f"quarentena {r['pct']}% > limite {r['limit_pct']:.0f}%")
        say(f"{r['contract']} | {r['batch_id']} | {r['ingested_at']} | {why}")
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
    from agentready_stack import lineage
    lin = lineage.check()
    summary = (f"Execução concluída. Marca d'água: {wm}. Fontes fora do SLA: {', '.join(stale) or 'nenhuma'}. "
               f"Pedidos ainda pendentes: {pend}. Linhagem: "
               + ("registrada no Marquez." if lin["ok"] else f"linhagem indisponível: {lin['reason']}"))
    say(summary)
    if not lin["ok"]:
        say(f"AVISO — linhagem indisponível: {lin['reason']} ({lin['url']}). A execução e as decisões não mudam "
            "(FR-013); só esta execução fica sem registro no Marquez.")
    return {"watermark": str(wm), "stale_sources": stale, "pending_requests": pend, "summary": summary,
            "lineage": lin}


def observe() -> dict:
    """Etapa 5a (folha, Fase 2). Imprime os 4 pilares desta execução (o mesmo formato do
    `agentready observe`) e falha se algum pilar falhou. O agente NÃO depende desta tarefa."""
    from agentready_stack import observe as obs
    con = connect()
    try:
        vs = obs.verdicts(con)
    finally:
        con.close()
    say("Observabilidade — 4 pilares de dados desta execução:")
    say(obs.table(vs))
    failed = [v for v in vs if v["status"] == "fail"]
    warned = [v for v in vs if v["status"] == "warn"]
    if warned:
        say(f"{len(warned)} aviso(s) de histórico insuficiente: aviso não bloqueia nada.")
    if failed:
        say(f"ATENÇÃO — {len(failed)} pilar(es) falharam. Detalhes e histórico no relatório de observabilidade.")
        raise obs.ObservabilityAlert("pilares com falha: " + ", ".join(f"{v['pillar']}:{v['target']}" for v in failed))
    return {"verdicts": vs}


def build_report() -> dict:
    """Etapa 5b (folha, Fase 2). Relatório web do Elementary; falhar aqui é só um aviso."""
    from agentready_stack import observe as obs
    return obs.build_report()


def dumps(result: dict) -> str:
    return json.dumps(result, ensure_ascii=False, default=str)
