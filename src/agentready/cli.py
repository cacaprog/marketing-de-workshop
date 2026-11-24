"""CLI do workshop: `agentready <comando>` (ou `uv run agentready <comando>`)."""
from __future__ import annotations

import argparse
import json
import sys

from agentready import ui


def _con():
    from agentready.db import connect
    return connect()


def cmd_setup(a):
    from agentready.blocks import reset
    reset()
    ui.note("Pronto. Próximo passo: `agentready demo all` (ou demo 0..5).")


def cmd_demo(a):
    from agentready import blocks
    ui.PAUSE = ui.PAUSE and not a.no_pause
    if a.block == "all":
        blocks.run_all()
    elif a.block == "5":
        blocks.block5(a.incident)
    else:
        blocks.BLOCKS[int(a.block)]()


def cmd_pipeline(a):
    from agentready import pipeline
    r = pipeline.run()
    ui.table(r["contracts"], title="Contratos")
    ui.table(r["health"], title="Frescor")
    if r["blocked_by_observability"]:
        ui.note(f"Lotes barrados pela observabilidade: {r['blocked_by_observability']}")


def cmd_agent(a):
    from agentready.agent import NaiveAgent, ReadyAgent
    con = _con()
    rep = NaiveAgent().run(con) if a.kind == "naive" else ReadyAgent(a.brain, a.gullible).run(con, a.request)
    ui.report(rep)


def cmd_ask(a):
    from agentready import semantic
    req = semantic.interpret(a.question)
    ui.console.print(f"métricas={req.metrics} dimensões={req.group_by} janela={req.window_days}d")
    sql, rs = semantic.query(_con(), req)
    ui.sql(sql)
    ui.table(rs)


def cmd_health(a):
    from agentready import capabilities as cap
    h = cap.get_data_health(_con())
    ui.table(h["sources"], title="Frescor por fonte")
    ui.table(h["quarantine"], title="Quarentena por contrato")
    ui.console.print(h["versions"])


def cmd_quarantine(a):
    from agentready.db import rows
    ui.table(rows(_con(), f"SELECT batch_id, violations, payload FROM quarantine.{a.table} LIMIT {a.limit}"))


def cmd_budgets(a):
    from agentready.db import rows
    con = _con()
    ui.budgets(rows(con, "SELECT * FROM ops.campaigns ORDER BY 1"))
    ui.table(rows(con, "SELECT change_id, campaign_id, action, old_value, new_value, actor, rolled_back, changed_at "
                       "FROM ops.change_log ORDER BY changed_at"), title="Histórico de alterações")


def cmd_approvals(a):
    from agentready import capabilities as cap
    ui.table(cap.pending_approvals(_con()), ["request_id", "action", "params", "reason", "trace_id"], "Pendentes")


def cmd_decide(a, approve: bool):
    from agentready import capabilities as cap
    res = cap.decide_approval(_con(), a.request_id, a.by, approve)
    if isinstance(res, str):
        ui.console.print(res)
    else:
        ui.console.print(f"{res.status}: {res.message}")
        ui.checks(res.to_dict())


def cmd_rollback(a):
    from agentready import capabilities as cap
    ui.console.print(cap.rollback(_con(), a.change_id, a.by))


def cmd_autonomy(a):
    from agentready import autonomy
    con = _con()
    if a.level:
        autonomy.set_override(con, None if a.level == "clear" else a.level)
    ui.console.print(f"override global: {autonomy.get_override(con) or '(nenhum — vale config/autonomy.yaml)'}")


def cmd_trace(a):
    from agentready import tracing
    from agentready.settings import TRACES_DIR
    if not a.trace_id:
        ui.table([{"trace_id": t, "raiz": n, "inicio": s} for t, n, s in tracing.trace_ids()], title="Traces")
        return
    spans = tracing.load(a.trace_id)
    if not spans:
        sys.exit(f"trace {a.trace_id} não encontrado")
    ui.trace_tree(tracing.tree(spans))
    tid = spans[0]["trace_id"]
    out = TRACES_DIR / f"{tid}.html"
    out.write_text(tracing.render_html(tid), encoding="utf-8")
    ui.note(f"HTML: {out}")


def cmd_verify(a):
    from agentready import tracing
    ok, n, msg = tracing.verify_chain()
    ui.console.print(f"[{'green' if ok else 'red'}]{msg}[/] ({n} registros)")
    sys.exit(0 if ok else 1)


def cmd_observe(a):
    from agentready import observability
    ui.table(observability.report(_con()), ["pillar", "target", "ok", "detail"], "5 pilares de observabilidade")


def cmd_lineage(a):
    from agentready import observability
    tree = ui.Tree(f"[bold]{a.node}[/]")

    def add(node, children):
        for k, v in children.items():
            add(node.add(k), v)
    add(tree, observability.downstream(a.node))
    ui.console.print(tree)
    if a.since:
        ui.table(observability.decisions_since(_con(), a.since), title=f"Decisões do agente desde {a.since}")


def cmd_incident(a):
    from agentready import incidents, pipeline
    con = _con()
    if a.action == "inject":
        r = incidents.inject(con, a.kind)
        con.close()
        pipeline.run()
        ui.console.print(f"[bold red]🚨 {r['incident_id']} injetado às {r['injected_at'][:19]}[/] — pipeline reprocessado.")
    elif a.action == "detect":
        r = incidents.mark_detected(con)
        ui.console.print(f"Detecção registrada: {r['detected_at']}")
    elif a.action == "resolve":
        r = incidents.resolve(con)
        con.close()
        pipeline.run()
        ui.console.print(json.dumps(r, default=str, ensure_ascii=False, indent=2))
    elif a.action == "reveal":
        ui.console.print(incidents.reveal(con))
    elif a.action == "list":
        ui.console.print("\n".join(f"{k}: {v}" for k, v in incidents.KINDS.items()))


def cmd_backfill(a):
    from agentready import generate, pipeline
    con = _con()
    n = generate.backfill_meta(con)
    con.close()
    pipeline.run()
    ui.console.print(f"{n} conversões da Meta recebidas e pipeline reprocessado.")


def cmd_mcp(a):
    from agentready.mcp_server import main
    main()


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="agentready", description="Workshop: dados prontos para IA agêntica (marketing)")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("setup", help="gera o cenário e roda o pipeline (reset completo)").set_defaults(fn=cmd_setup)
    d = sub.add_parser("demo", help="roteiro narrado: 0..5 ou all")
    d.add_argument("block", choices=["0", "1", "2", "3", "4", "5", "all"])
    d.add_argument("--no-pause", action="store_true")
    d.add_argument("--incident", default="centavos", help="incidente do Bloco 5 (ou 'random')")
    d.set_defaults(fn=cmd_demo)
    sub.add_parser("pipeline", help="Bronze -> contratos -> Silver -> Gold").set_defaults(fn=cmd_pipeline)
    ag = sub.add_parser("agent", help="roda um agente")
    ag.add_argument("kind", choices=["naive", "ready"])
    ag.add_argument("--brain", choices=["rules", "claude"], default="rules")
    ag.add_argument("--gullible", action="store_true", help="simula agente convencido por injeção de prompt")
    ag.add_argument("--request", default="Otimize o orçamento diário das campanhas conforme a política.")
    ag.set_defaults(fn=cmd_agent)
    ask = sub.add_parser("ask", help="pergunta em linguagem natural -> camada semântica")
    ask.add_argument("question")
    ask.set_defaults(fn=cmd_ask)
    sub.add_parser("health", help="frescor, quarentena e versões").set_defaults(fn=cmd_health)
    q = sub.add_parser("quarantine", help="inspeciona a dead-letter queue")
    q.add_argument("table", nargs="?", default="conversions")
    q.add_argument("--limit", type=int, default=15)
    q.set_defaults(fn=cmd_quarantine)
    sub.add_parser("budgets", help="estado vivo das campanhas e histórico").set_defaults(fn=cmd_budgets)
    sub.add_parser("approvals", help="fila de aprovação humana").set_defaults(fn=cmd_approvals)
    for name, flag in (("approve", True), ("reject", False)):
        x = sub.add_parser(name)
        x.add_argument("request_id")
        x.add_argument("--by", default="gerente.growth")
        x.set_defaults(fn=lambda a, f=flag: cmd_decide(a, f))
    rb = sub.add_parser("rollback")
    rb.add_argument("change_id")
    rb.add_argument("--by", default="humano")
    rb.set_defaults(fn=cmd_rollback)
    au = sub.add_parser("autonomy", help="override global: shadow|supervised|guarded|full|clear")
    au.add_argument("level", nargs="?")
    au.set_defaults(fn=cmd_autonomy)
    tr = sub.add_parser("trace", help="lista traces ou mostra um (id, prefixo ou 'last')")
    tr.add_argument("trace_id", nargs="?")
    tr.set_defaults(fn=cmd_trace)
    sub.add_parser("verify", help="verifica a cadeia de hash do log de auditoria").set_defaults(fn=cmd_verify)
    sub.add_parser("observe", help="5 pilares de observabilidade").set_defaults(fn=cmd_observe)
    li = sub.add_parser("lineage", help="impacto a jusante de um nó")
    li.add_argument("node", nargs="?", default="feed:ga4 (site)")
    li.add_argument("--since", help="lista decisões do agente desde este timestamp")
    li.set_defaults(fn=cmd_lineage)
    inc = sub.add_parser("incident", help="inject [tipo] | detect | resolve | reveal | list")
    inc.add_argument("action", choices=["inject", "detect", "resolve", "reveal", "list"])
    inc.add_argument("kind", nargs="?")
    inc.set_defaults(fn=cmd_incident)
    sub.add_parser("backfill-meta", help="corrige o feed da Meta (chegam os lotes atrasados)").set_defaults(fn=cmd_backfill)
    sub.add_parser("mcp", help="inicia o servidor MCP (stdio)").set_defaults(fn=cmd_mcp)
    a = p.parse_args(argv)
    if getattr(a, "incident", None) == "random":
        a.incident = None
    from agentready.semantic import SemanticError
    try:
        a.fn(a)
    except (SemanticError, RuntimeError, ValueError) as e:
        ui.console.print(f"[bold red]recusado:[/] {e}")
        sys.exit(2)


if __name__ == "__main__":
    main()
