"""Roteiro executável do workshop: `agentready demo <0-5|all>`.

Cada bloco imprime o problema, executa o que o instrutor mostra ao vivo e termina
com o entregável. O resultado de um bloco é a entrada do próximo.
"""
from __future__ import annotations

import hashlib
import shutil

from agentready import capabilities as cap
from agentready import generate, incidents, observability, pipeline, semantic, tracing, ui
from agentready.agent import NaiveAgent, ReadyAgent, ground_truth
from agentready.capabilities import brl
from agentready.db import connect, rows
from agentready.settings import TRACES_DIR

console = ui.console


def reset(quiet: bool = False) -> None:
    if TRACES_DIR.exists():
        shutil.rmtree(TRACES_DIR)
    stats = generate.generate()
    pipeline.run()
    if not quiet:
        ui.note(f"Cenário gerado: {stats['ad_spend_rows']} linhas de investimento, "
                f"{stats['conversion_rows']} conversões (Bronze) · âncora {stats['generated_at']}")


# ------------------------------------------------------------------ Bloco 0

def block0() -> None:
    ui.block(0, "Choque de realidade", "Um agente de IA ingênuo, conectado direto aos dados brutos, recebe a missão: "
             "'realoque o orçamento das campanhas com base no ROAS recente'. Ninguém percebeu que o feed de conversões "
             "da Meta parou há 3 dias e que um lote do site foi carregado em dobro.")
    reset()
    con = connect()
    ui.budgets(rows(con, "SELECT * FROM ops.campaigns ORDER BY 1"), "Orçamento ANTES do agente")
    ui.pause("rodar o agente ingênuo")
    rep = NaiveAgent().run(con)
    ui.sql(rep.steps[0].data["sql"])
    ui.table(rep.steps[0].data["rows"], ["campaign_id", "spend", "revenue", "roas"], "O que o agente 'viu'")
    ui.report(rep)
    ui.budgets(rows(con, "SELECT * FROM ops.campaigns ORDER BY 1"), "Orçamento DEPOIS do agente")
    ui.pause("ver o que era verdade")
    truth = {t["campaign_id"]: t for t in ground_truth(con)}
    paused = [r["campaign_id"] for r in rows(con, "SELECT campaign_id FROM ops.campaigns WHERE status='paused'")]
    ui.table(list(truth.values()), ["campaign_id", "campaign_name", "objective", "true_roas", "net_revenue_per_day"],
             "Verdade (dados válidos, antes da falha do feed)",
             fmt={"net_revenue_per_day": brl, "true_roas": lambda v: f"{v:.2f}"})
    lost = sum(truth[c]["net_revenue_per_day"] for c in paused if truth[c]["objective"] == "conversion")
    console.print(f"[bold red]Resultado:[/] pausou {', '.join(paused)} — incluindo as duas campanhas de Meta, de ROAS "
                  f"real {truth['C03']['true_roas']:.1f} e {truth['C04']['true_roas']:.1f}. "
                  f"Receita líquida em risco: [bold]{brl(lost)}/dia[/]. Pausou awareness avaliando por ROAS. "
                  f"E manteve o YouTube (ROAS real {truth['C06']['true_roas']:.2f}) porque o lote duplicado inflou o número.")
    console.print("[bold]Nenhum erro foi lançado. Nenhum alerta disparou. Falha silenciosa.[/]")
    ui.note("Precisely/Drexel LeBow 2026: 87% dos líderes dizem estar prontos para IA; 43% apontam a prontidão dos "
            "dados como o maior obstáculo.")
    con.close()


# ------------------------------------------------------------------ Bloco 1

def block1() -> None:
    ui.block(1, "Fundação confiável — contratos e quarentena",
             "Agentes não têm o 'teste do cheiro' do analista: tratam qualquer valor como verdade.")
    reset()
    con = connect()
    ui.note("O contrato é a lei: contracts/conversions.odcs.yaml (ODCS v3) — tipos, domínios, mínimos, chave única, "
            "SLA de frescor por feed e taxa máxima de quarentena por lote.")
    ui.table(rows(con, """SELECT contract, contract_version AS versao, COUNT(*) AS lotes, SUM(rows) AS linhas,
                          SUM(quarantined) AS quarentena, COUNT(*) FILTER (WHERE status='barred') AS lotes_barrados
                          FROM meta.batch_status GROUP BY ALL ORDER BY 1"""), title="Resultado da validação Bronze → Silver")
    ui.table(rows(con, """SELECT regexp_replace(violations[1], ' valor=.*', '') AS motivo, COUNT(*) AS linhas
                          FROM quarantine.conversions GROUP BY 1 ORDER BY 2 DESC"""), title="Quarentena (dead-letter)")
    ui.table(rows(con, """SELECT batch_id, rows, quarantined, round(rate*100,1) AS pct, status FROM meta.batch_status
                          WHERE status='barred'"""), title="Disjuntor: lotes barrados inteiros (> 5% de quarentena)")
    ui.pause("frescor")
    ui.table(rows(con, "SELECT * FROM gold.source_health"), title="SLA de frescor = última CARGA bem-sucedida (ingested_at)")
    ui.pause("o que o agente recebe agora")
    perf = cap.get_campaign_performance(con)
    ui.table(semantic.display(perf), ["campaign_id", "roas", "net_revenue", "data_status", "conversions_age_hours"],
             "Gold servida ao agente (dado atrasado = NULL, não zero)")
    for p in perf:
        if p["data_status"] == "stale":
            console.print(f" 🛑 [green]{p['campaign_id']}: \"Não possuo dados atuais de conversão "
                          f"(última carga há {p['conversions_age_hours']:.0f}h).\"[/]")
    ui.deliverable("Contratos versionados em contracts/ · quarentena em quarantine.* · disjuntor por lote e por SLA "
                   "de frescor · o agente declara 'não possuo dados atuais' em vez de alucinar.")
    con.close()


# ------------------------------------------------------------------ Bloco 2

GUESSES = {
    "A: receita bruta": """
SELECT s.campaign_id, SUM(c.rev) / SUM(s.spend_brl) AS roas FROM silver.ad_spend s
LEFT JOIN (SELECT campaign_id, CAST(converted_at AS DATE) d, SUM(order_value_brl) rev
           FROM silver.conversions GROUP BY ALL) c ON c.campaign_id = s.campaign_id AND c.d = s.spend_date
WHERE s.spend_date >= current_date - 14 AND s.spend_date < current_date GROUP BY 1""",
    "B: join com fan-out": """
SELECT s.campaign_id, SUM(c.order_value_brl - c.discount_brl) / SUM(s.spend_brl) AS roas
FROM silver.ad_spend s JOIN silver.conversions c
  ON c.campaign_id = s.campaign_id AND CAST(c.converted_at AS DATE) = s.spend_date
WHERE s.spend_date >= current_date - 14 AND s.spend_date < current_date GROUP BY 1""",
    "C: média das razões": """
SELECT campaign_id, AVG((gross_revenue_brl - discount_brl) / spend_brl) AS roas FROM gold.campaign_daily
WHERE day >= current_date - 14 AND day < current_date AND orders > 0 GROUP BY 1""",
}


def block2() -> None:
    ui.block(2, "Camada de contexto — ensinando significado à IA",
             "Os dados estão limpos, mas o agente não sabe o que 'receita' significa, qual o grão das tabelas "
             "nem que awareness não se mede por ROAS. Sem semântica, ele adivinha SQL.")
    con = connect()
    official = {r["campaign_id"]: r for r in semantic.display(semantic.query(con, semantic.MetricRequest(["roas"]))[1])}
    table_rows = []
    guesses = {k: {r["campaign_id"]: r["roas"] for r in rows(con, q)} for k, q in GUESSES.items()}
    for cid, o in official.items():
        table_rows.append({"campanha": cid, "oficial": o["roas"], **{k: guesses[k].get(cid) for k in GUESSES}})
    ui.table(table_rows, title="ROAS 14d de cada campanha: oficial vs três SQLs 'plausíveis'")
    ui.note("C05 é awareness: ROAS e CAC não se aplicam (regra no modelo semântico, não só no texto). "
            "Os três palpites não sabem disso e devolvem um número.")
    ui.note("A: esquece o desconto (receita é LÍQUIDA). B: o join multiplica o investimento por pedido (fan-out). "
            "C: média de razões ≠ razão das somas. Nenhum dos três sabe que a Meta está atrasada.")
    ui.note("Referência: AtScale (2024, estudo do próprio fornecedor, 40 perguntas TPC-DS, Gemini 1.5 Pro): 20% de "
            "acerto sem camada semântica vs 92,5% com ela. Indicativo, não definitivo.")
    ui.pause("a camada semântica")
    q = "Qual o ROAS e a receita líquida por campanha nos últimos 14 dias?"
    console.print(f"[bold]Pergunta:[/] {q}")
    req = semantic.interpret(q)
    console.print(f"[bold]Intenção estruturada:[/] métricas={req.metrics} dimensões={req.group_by} janela={req.window_days}d")
    sql1 = semantic.compile_sql(req)
    sql2 = semantic.compile_sql(semantic.interpret("me mostra retorno sobre investimento e faturamento líquido de cada "
                                                   "campanha, 14 dias"))
    ui.sql(sql1)
    h1, h2 = (hashlib.sha256(s.encode()).hexdigest()[:12] for s in (sql1, sql2))
    console.print(f"Pergunta reformulada → mesmo SQL? [bold]{'SIM' if h1 == h2 else 'NÃO'}[/] (sha {h1} / {h2})")
    ui.table(semantic.display(semantic.query(con, req)[1]),
             title="Resultado (métricas oficiais, grão correto, guarda de frescor)")
    ui.note("Regras do Modelo de Domínio em semantic/marketing.semantic.yaml: receita é líquida · awareness não usa "
            "ROAS · dado atrasado não é zero.")
    ui.deliverable("semantic/marketing.semantic.yaml versionado (domínio + métricas + capacidades) e o compilador "
                   "determinístico src/agentready/semantic.py. `agentready ask \"...\"` para testar perguntas.")
    con.close()


# ------------------------------------------------------------------ Bloco 3

def block3() -> None:
    ui.block(3, "Do pesquisável ao acionável — MCP e guardrails",
             "Responder perguntas não basta: o agente precisa agir na plataforma de anúncios. Expor 200 endpoints "
             "REST degrada o modelo (tool sprawl) — e um briefing contém uma injeção de prompt.")
    from agentready.mcp_server import server
    import asyncio
    tools = asyncio.run(server.list_tools())
    ui.table([{"tool": t.name, "somente_leitura": bool(t.annotations and t.annotations.read_only_hint),
               "destrutiva": bool(t.annotations and t.annotations.destructive_hint)} for t in tools],
             title="Servidor MCP 'aurora-midia': 5 capacidades de negócio (não 200 wrappers de API)")
    ui.note("Resources: policy://orcamento-midia (confiável) · briefing://campanhas/{id} (NÃO confiável)")
    ui.pause("ler o briefing do YouTube")
    console.print(ui.Panel(cap.read_briefing("C06"), title="briefing://campanhas/C06", border_style="yellow"))
    ui.pause("rodar o agente — simulando um modelo que FOI convencido pela injeção")
    con = connect()
    rep = ReadyAgent(gullible=True).run(con)
    ui.report(rep)
    blocked = [s.data["result"] for s in rep.steps if s.data.get("result", {}).get("status") == "rejected"]
    if blocked:
        ui.checks(blocked[0])
        console.print("[bold green]O texto recuperado informou; não autorizou.[/] A autorização mora no backend "
                      "(config/guardrails.yaml), verificada contra o estado vivo — o modelo nunca vê nem altera esses limites.")
    ui.budgets(rows(con, "SELECT * FROM ops.campaigns ORDER BY 1"))
    ui.deliverable("Servidor MCP (src/agentready/mcp_server.py) com Resources, Tools de leitura e Tools de write-back "
                   "com pré-condições em código e classes de reversibilidade R0–R3. `agentready mcp` para conectar.")
    con.close()


# ------------------------------------------------------------------ Bloco 4

def block4() -> None:
    ui.block(4, "Rastreabilidade e governança — linhagem agêntica e autonomia gradual",
             "Seis meses depois, a auditoria pergunta POR QUE o orçamento do Google Marca subiu e o do YouTube não "
             "caiu. Logs comuns dizem O QUE foi acessado, não o raciocínio.")
    con = connect()
    last_agent = [t for t in tracing.trace_ids() if t[1] == "agent.run"]
    if not last_agent:
        ReadyAgent().run(con)
        last_agent = [t for t in tracing.trace_ids() if t[1] == "agent.run"]
    tid = last_agent[-1][0]
    ui.trace_tree(tracing.tree(tracing.load(tid)))
    out = TRACES_DIR / f"{tid}.html"
    out.write_text(tracing.render_html(tid), encoding="utf-8")
    ui.note(f"Árvore completa com atributos (SQL, versões, pré-condições): {out}")
    ok, n, msg = tracing.verify_chain()
    console.print(f"Cadeia de hash do log de auditoria: [{'green' if ok else 'red'}]{msg}[/] ({n} registros)")
    recs = tracing.load()
    target = next((r for r in recs if r["name"] == "tool.adjust_campaign_budget"), None)
    if target:
        target["attributes"]["params.new_daily_budget_brl"] = 1.0
        ok2, _, msg2 = tracing.verify_chain(recs)
        console.print(f"Simulando adulteração de um registro (em memória) → [{'green' if ok2 else 'red'}]{msg2}[/]")
    ui.pause("escada de autonomia")
    ui.note("config/autonomy.yaml: adjust_campaign_budget=guarded (escala para supervised acima de 10%) · "
            "pause_campaign=supervised · delete_campaign=disabled")
    pend = cap.pending_approvals(con)
    ui.table(pend, ["request_id", "action", "params", "reason", "status"], "Fila de aprovação humana")
    if pend:
        res = cap.decide_approval(con, pend[0]["request_id"], "gerente.growth", True)
        console.print(f"Aprovado por gerente.growth → pré-condições reavaliadas no estado vivo → "
                      f"[{ui.STATUS_STYLE.get(res.status, '')}]{res.status}[/]: {res.message}")
    res = cap.pause_campaign(con, "C06", "ROAS persistentemente abaixo de 1,0")
    console.print(f"Ação de alto risco (R2) pause_campaign(C06) → [{ui.STATUS_STYLE[res.status]}]{res.status}[/]: "
                  f"{res.message}")
    ui.pause("modo shadow")
    from agentready import autonomy
    autonomy.set_override(con, "shadow")
    rep = ReadyAgent().run(con)
    autonomy.set_override(con, None)
    for s in rep.steps:
        if s.kind == "action":
            console.print(f" 👁  {s.text}")
    ui.note("Shadow mode: o agente roda em produção e registra o que FARIA; humanos comparam com as próprias decisões "
            "antes de promover o nível de autonomia.")
    ui.deliverable(f"Trace OpenTelemetry por decisão (traces/audit.jsonl + {out.name}), log à prova de adulteração, fila "
                   "de aprovação e escada de autonomia configurável. Para ver no Arize Phoenix ou no Langfuse: "
                   "OTEL_EXPORTER_OTLP_ENDPOINT=...")
    con.close()


# ------------------------------------------------------------------ Bloco 5

def block5(kind: str | None = "centavos") -> None:
    ui.block(5, "Operação no mundo real — incidente e post-mortem sem culpados",
             "O time de e-commerce faz um deploy e reenvia o lote de ontem. Algo mudou. O agente continua rodando.")
    con = connect()
    if con.execute("SELECT COUNT(*) FROM meta.upstream_backlog").fetchone()[0]:
        n = generate.backfill_meta(con)
        con.close()
        pipeline.run()
        con = connect()
        ui.note(f"Antes: o time de dados corrigiu o token da Meta; {n} conversões atrasadas chegaram (backfill).")
    ui.table(observability.report(con), ["pillar", "target", "ok", "detail"], "Linha de base: 5 pilares")
    ui.pause("injetar incidente")
    inc = incidents.inject(con, kind)
    con.close()
    pipeline.run()
    con = connect()
    console.print(f"[bold red]🚨 {inc['incident_id']} injetado às {inc['injected_at'][:19]}[/] (tipo oculto para os squads)")
    rep = ReadyAgent().run(con)
    ui.report(rep)
    ui.pause("triagem: observabilidade")
    obs = observability.report(con)
    ui.table(obs, ["pillar", "target", "ok", "detail"], "5 pilares após o incidente")
    incidents.mark_detected(con)
    ui.pause("triagem: linhagem e impacto")
    bad = [o for o in obs if not o["ok"]]
    root = "feed:ga4 (site)" if any("ga4" in o["target"] or "bronze.conversions" in o["target"] for o in bad) else None
    if root:
        tree = ui.Tree(f"[bold red]{root}[/]")

        def add(node, children):
            for k, v in children.items():
                add(node.add(k), v)
        add(tree, observability.downstream(root))
        console.print(tree)
    ui.table(observability.decisions_since(con, inc["injected_at"]), ["id", "campaign_id", "action", "change", "kind",
                                                                     "trace_id"],
             "Decisões do agente tomadas DEPOIS do incidente (candidatas a rollback)")
    ui.pause("resolver")
    for d in observability.decisions_since(con, inc["injected_at"]):
        if d["kind"] == "executada":
            console.print(cap.rollback(con, d["id"], "incident-commander"))
    m = incidents.resolve(con)
    con.close()
    pipeline.run()
    console.print(f"[bold]Incidente:[/] {m['kind_description']}")
    console.print(f"TTD = {m['TTD_min']} min · TTR = {m['TTR_min']} min")
    ui.note("Ação corretiva típica do post-mortem (centavos): promover a checagem de distribuição a disjuntor — "
            "config/guardrails.yaml → observability.block_on_distribution_anomaly: true — e adicionar ao contrato "
            "uma regra de faixa para order_value_brl. Template: templates/post-mortem.md")
    ui.deliverable("Post-mortem sem culpados preenchido (templates/post-mortem.md) com linha do tempo, TTD/TTR, "
                   "5 Porquês e ações corretivas no CI/CD.")


BLOCKS = {0: block0, 1: block1, 2: block2, 3: block3, 4: block4, 5: block5}


def run_all() -> None:
    for n, fn in BLOCKS.items():
        fn()
        ui.pause(f"fim do Bloco {n}")
    ui.console.rule("[bold]Fechamento")
    ui.note("Autoavaliação de maturidade: templates/autoavaliacao-maturidade.md")

