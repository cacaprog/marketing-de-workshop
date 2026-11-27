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


def _brain(a, allow_rules: bool = True):
    """Monta o cérebro a partir de --brain/--llm-model/--llm-url e testa o acesso ANTES de rodar."""
    from agentready import llm
    try:
        if a.brain == "rules":
            if not allow_rules:
                raise llm.LLMError("as perguntas precisam de um modelo de linguagem; para a camada semântica "
                                   "determinística use agentready ask.")
            return llm.BrainSpec("rules")
        if a.brain == "local":
            spec = llm.parse_brain_spec(f"local:{a.llm_model}" if a.llm_model else "local", default_url=a.llm_url)
        else:
            spec = llm.parse_brain_spec(a.brain)
        llm.adapter_for(spec).probe()
        return spec
    except (llm.LLMError, ValueError) as e:
        ui.console.print(f"[bold red]Erro:[/] {e}")
        sys.exit(1)


def cmd_agent(a):
    from agentready.agent import NaiveAgent, ReadyAgent
    if a.gullible and a.brain != "rules":
        ui.console.print("[bold red]Erro:[/] --gullible simula um agente convencido; só vale com --brain rules.")
        sys.exit(1)
    spec = _brain(a)
    con = _con()
    if a.kind == "naive":
        rep = NaiveAgent(spec).run(con, a.request if spec.kind != "rules" else None)
    else:
        rep = ReadyAgent(spec, a.gullible).run(con, a.request)
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


def _confirm(lines: list[str], yes: bool) -> None:
    for line in lines:
        ui.console.print(line)
    if yes:
        return
    try:
        ok = input("Continuar? [s/N] ").strip().lower() in ("s", "sim", "y", "yes")
    except EOFError:
        ok = False
    if not ok:
        ui.console.print("Cancelado. Use --sim para pular esta pergunta.")
        sys.exit(1)


def cmd_compare(a):
    from agentready import compare, llm
    try:
        specs = llm.parse_brain_list(a.brains, default_url=a.llm_url)
    except (llm.LLMError, ValueError) as e:
        ui.console.print(f"[bold red]Erro:[/] {e}")
        sys.exit(1)
    if a.modo == "perguntas":
        from agentready import perguntas
        sys.exit(perguntas.cmd_compare(specs, a.runs, a.sim))
    conds = {"ambas": compare.CONDITIONS, "com": ("com_contexto",), "sem": ("sem_contexto",)}[a.condicoes]
    total = sum(len(conds) * (1 if s.kind == "rules" else a.runs) for s in specs)
    lines = [f"Plano: {', '.join(s.label for s in specs)} · {', '.join(compare.COND_LABEL[c] for c in conds)} · "
             f"até {total} execuções.",
             "A comparação recria o cenário a cada execução (como o setup)."]
    if any(s.kind == "claude" for s in specs):
        lines.append("Usa a API da Anthropic (cobrada por token).")
    _confirm(lines, a.sim)

    def progress(n, total_, r):
        n_ = len(r.executed)
        q_ = len(r.queued)
        extra = (f"{n_} {'ação' if n_ == 1 else 'ações'}" + (f", {q_} {'pedido' if q_ == 1 else 'pedidos'} de aprovação"
                                                              if q_ else "")
                 if r.outcome != "falhou" else (r.failure or "")[:80])
        ui.console.print(f"[{n}/{total_}] {r.brain} · {compare.COND_LABEL[r.condition]} · {r.index} … "
                         f"{r.outcome} ({extra}, {r.seconds or 0:.0f} s)")
    doc = compare.run_comparison(specs, a.runs, conds, progress)
    ui.comparison_table(doc["summary"])
    for s in doc["skipped"]:
        ui.console.print(f"[yellow]Pulado:[/] {s['brain']} — {s['reason']}")
    ui.console.print(f"Resultados: {doc['path']}")
    if not doc["runs"]:
        sys.exit(2)


def cmd_perguntas(a):
    from agentready import perguntas
    try:
        if a.mostrar:
            perguntas.mostrar(a.mostrar, a.ids, pause=ui.PAUSE and not a.no_pause)
            return
        spec = _brain(a, allow_rules=False)
        lines = ["As perguntas recriam o cenário (como o setup): o estado da demonstração ao vivo será perdido."]
        if spec.kind == "claude":
            lines.append("Usa a API da Anthropic (cobrada por token).")
        _confirm(lines, a.sim)
        perguntas.rodar(spec, a.ids, pause=ui.PAUSE and not a.no_pause)
    except (perguntas.PerguntaInvalida, FileNotFoundError) as e:
        ui.console.print(f"[bold red]Erro:[/] {e}")
        sys.exit(1)


def cmd_chat(a):
    from agentready import perguntas
    spec = _brain(a, allow_rules=False)
    perguntas.conversar(spec, "sem_contexto" if a.sem_contexto else "com_contexto")


def _brain_args(parser, choices=("rules", "claude", "local"), default="rules") -> None:
    parser.add_argument("--brain", choices=list(choices), default=default,
                        help="rules (determinístico), claude (API da Anthropic) ou local (Ollama, llama.cpp)")
    parser.add_argument("--llm-model", help="modelo local (ex.: qwen2.5:14b); padrão: AGENTREADY_LLM_MODEL")
    parser.add_argument("--llm-url", help="URL do servidor local; padrão: AGENTREADY_LLM_BASE_URL ou "
                                          "http://localhost:11434/v1 (Ollama)")


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
    _brain_args(ag)
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
    cp = sub.add_parser("compare", help="compara cérebros com e sem a camada de contexto")
    cp.add_argument("--brains", required=True, help="ex.: rules,claude,local:qwen2.5:14b,local:<m>@http://localhost:8081/v1")
    cp.add_argument("--runs", type=int, default=3, choices=range(1, 21), metavar="N", help="execuções por cérebro e condição (1–20)")
    cp.add_argument("--condicoes", choices=["ambas", "com", "sem"], default="ambas")
    cp.add_argument("--modo", choices=["acoes", "perguntas"], default="acoes")
    cp.add_argument("--llm-url", help="URL padrão para cérebros local:<modelo> sem @url")
    cp.add_argument("--sim", action="store_true", help="não pergunta antes de recriar o cenário")
    cp.set_defaults(fn=cmd_compare)
    pg = sub.add_parser("perguntas", help="perguntas de negócio respondidas com e sem a camada de contexto")
    _brain_args(pg, default="local")
    pg.add_argument("--ids", help="só estas perguntas (ids separados por vírgula)")
    pg.add_argument("--no-pause", action="store_true")
    pg.add_argument("--sim", action="store_true", help="não pergunta antes de recriar o cenário")
    pg.add_argument("--mostrar", metavar="ARQUIVO", help="reapresenta uma execução gravada, sem modelo nem rede")
    pg.set_defaults(fn=cmd_perguntas)
    ch = sub.add_parser("chat", help="conversa livre com um modelo, com ou sem a camada de contexto (só leitura)")
    _brain_args(ch, default="local")
    ch.add_argument("--sem-contexto", action="store_true", help="só dados brutos da Bronze")
    ch.set_defaults(fn=cmd_chat)
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
