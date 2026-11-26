"""CLI `agentready-stack`: as mesmas tarefas que o DAG roda, executáveis à mão.

  agentready-stack task ingest      [--params JSON]
  agentready-stack task run-agent   [--brain rules|claude] [--gullible] [--dag-run-id ID]
  agentready-stack task apply       --request-id REQ [--payload JSON] [--timeout-at ISO]
  agentready-stack task close       [--dag-run-id ID]
  agentready-stack task alert
  agentready-stack task observe | report                                 (Fase 2, observabilidade)
  agentready-stack parity           --scenario manha|pos_backfill|supervisionado|incidente_<tipo>|todos
  agentready-stack doctor                                                             (polimento)
  agentready-stack incident detect|resolve|reveal|list                       (Fase 2, Bloco 5)
  agentready-stack decisions --since ISO · agentready-stack lineage-check     (Fase 2)
  agentready-stack traces [--limit N] · agentready-stack rollback CHG [--by ATOR]  (Fase 3, traces)

Fase 3 (traces): todo subcomando herda o contexto do Airflow via TRACEPARENT (os spans do agente e da
stack entram no trace da execução) e esvazia os exportadores antes de sair, com tempo limitado.

Contrato de saída das tarefas: relato em pt-BR no stdout e, na ÚLTIMA linha, o resultado em JSON
(o DAG lê essa linha como XCom). Códigos: 0 ok · 1 falha da tarefa · 2 erro de ambiente.
"""
from __future__ import annotations

import argparse
import json
import os
import sys


def _env_error(e: Exception) -> int:
    msg = str(e)
    if "lock" in msg.lower() or "Conflicting lock" in msg:
        print("ERRO de ambiente: o warehouse DuckDB está aberto por outro processo (um escritor por vez). "
              "Espere a execução atual terminar ou pare quem estiver com o arquivo aberto.", file=sys.stderr)
    else:
        print(f"ERRO de ambiente: {msg}", file=sys.stderr)
    return 2


def _ingest_fonte(a) -> int:
    """Fase 4: uma carga de uma fonte (roda no venv da ingestão; não importa o agente)."""
    from agentready_stack import ingestion
    if not a.fonte:
        print("uso: agentready-stack task ingest-fonte <ads|ga4|meta_capi|catalogo> --dag-run-id ID", file=sys.stderr)
        return 1
    try:
        out = ingestion.run_source(a.fonte, a.dag_run_id)
    except ingestion.IngestionConfigError as e:
        print(f"ERRO de configuração da ingestão: {e}", file=sys.stderr)
        return 1
    except Exception as e:  # noqa: BLE001
        if type(e).__name__ in ("IOException", "ConnectionException") or "lock" in str(e).lower():
            return _env_error(e)
        raise
    print(ingestion.summary_line(out), flush=True)
    print(json.dumps(out, ensure_ascii=False, default=str), flush=True)
    return 0


def _fontes() -> int:
    """Fase 4: a última carga de cada fonte (ops.ingestion_loads)."""
    from agentready_stack import ingestion, warehouse
    con = warehouse.connect(read_only=True)
    try:
        ingestion_ok = con.execute("SELECT count(*) FROM information_schema.tables WHERE table_catalog='ops' "
                                   "AND table_name='ingestion_loads'").fetchone()[0]
        rows = con.execute("""SELECT fonte, status, lotes_novos, lotes_retirados, linhas, tentativas_http, motivo,
                                     terminado_em, dag_run_id FROM ops.ingestion_loads
                              QUALIFY row_number() OVER (PARTITION BY fonte ORDER BY terminado_em DESC) = 1
                              ORDER BY fonte""").fetchall() if ingestion_ok else []
    finally:
        con.close()
    if not rows:
        print("Nenhuma carga registrada ainda (rode o DAG: make run).")
    out = []
    for fonte, st, nov, ret, lin, tent, mot, quando, run in rows:
        d = {"fonte": fonte, "status": st, "lotes_novos": nov or [], "lotes_retirados": ret or [], "linhas": lin,
             "tentativas_http": tent, "motivo": mot, "terminado_em": quando, "dag_run_id": run}
        out.append(d)
        print(f"{quando:%d/%m %H:%M} · " + ingestion.summary_line(d | {"linhas": lin or 0}))
    print(json.dumps({"fontes": out}, ensure_ascii=False, default=str), flush=True)
    return 0


def _lake_cmd(a) -> int:
    """Fase 4: snapshots com nome, leitura de qualquer camada num ponto do lake, a Gold de uma decisão, restauração."""
    from agentready_stack import lake, warehouse

    def dump(o):
        print(json.dumps(o, ensure_ascii=False, default=str), flush=True)
    try:
        if a.cmd == "snapshots":
            con = warehouse.connect(read_only=True)
            try:
                marks = lake.snapshots(con, a.limit)
                atual = lake.current_snapshot(con)
            finally:
                con.close()
            print(f"Lake (DuckLake) no snapshot {atual}. Marcos, do mais novo para o mais antigo:")
            for m in marks:
                extra = (f" · lotes {', '.join(m['lotes'][:3])}{'…' if len(m['lotes']) > 3 else ''}" if m["lotes"] else "")
                inc = f" · incidente {m['incident_id']} aberto" if m["incident_id"] else ""
                print(f"  {m['checkpoint_id']} · snapshot {m['snapshot_id']} · {m['criado_em']:%d/%m %H:%M:%S} · "
                      f"{m['etapa']} · {m['dag_run_id'] or 'comando'} · {m['commits_desde_o_anterior']} commit(s)"
                      f"{extra}{inc}")
            dump({"atual": atual, "marcos": marks})
        elif a.cmd == "consultar-em":
            con = warehouse.connect(read_only=True)
            try:
                cols, rows = lake.consultar_em(con, a.tabela, a.em, a.filtro, a.limite)
            finally:
                con.close()
            print(f"{a.tabela} em {a.em} ({len(rows)} linha(s), até {a.limite}):")
            print(" | ".join(cols))
            for r in rows:
                print(" | ".join("" if v is None else str(v) for v in r))
            dump({"tabela": a.tabela, "em": a.em, "colunas": cols, "linhas": rows})
        elif a.cmd == "gold-em":
            from agentready.settings import guardrails
            con = warehouse.connect(read_only=True)
            try:
                g = lake.gold_as_of(con, a.decisao, guardrails()["optimization"]["lookback_days"])
            finally:
                con.close()
            d = g["decisao_detalhe"]
            print(f"Decisão {g['decisao']} (trace {g['trace_id']}) · execução {g['dag_run_id']} · o agente leu o "
                  f"snapshot {g['snapshot_id']} ({g['checkpoint_id']}).")
            if d:
                print("  " + " · ".join(f"{k}: {v}" for k, v in d.items()))
            print("Gold campanha×dia como o agente viu" + (f" ({g['campaign_id']})" if g["campaign_id"] else "") + ":")
            print(" | ".join(g["colunas"]))
            for r in g["linhas"]:
                print(" | ".join("" if v is None else str(v) for v in r))
            dump(g)
        elif a.cmd == "restaurar":
            con = warehouse.connect()
            try:
                r = lake.restore(con, a.para, a.motivo or "restauração manual", a.por)
            finally:
                con.close()
            print(f"Camadas de dados restauradas: snapshot {r['de_snapshot']} → {r['para_snapshot']} "
                  f"(novo snapshot {r['novo_snapshot']}; {r['tabelas']} tabelas). O estado operacional não mudou.")
            print(f"Para desfazer: {r['desfazer']}")
            dump(r)
    except lake.RestoreRefused as e:
        print(f"RECUSADO: {e}", file=sys.stderr)
        return 2
    except lake.NotFound as e:
        print(f"NÃO ENCONTRADO: {e}", file=sys.stderr)
        return 1
    except Exception as e:  # noqa: BLE001 — arquivo aberto por uma execução em andamento etc.
        if type(e).__name__ in ("IOException", "ConnectionException") or "lock" in str(e).lower():
            return _env_error(e)
        raise
    return 0


def _approvals() -> int:
    """Pedidos aguardando aprovação humana (função compartilhada sobre a conexão da stack; Fase 4: ops.duckdb).
    O `agentready approvals` da trilha padrão abriria o ops.duckdb com o conector compartilhado, que cria schemas
    vazios (bronze…ops) dentro dele e deixa `ops.x` ambíguo."""
    from agentready import capabilities
    from agentready_stack import warehouse
    con = warehouse.connect(read_only=True)
    try:
        pend = capabilities.pending_approvals(con)
    finally:
        con.close()
    if not pend:
        print("Nenhum pedido aguardando aprovação.")
    for p in pend:
        print(f"{p['request_id']} · {p['action']} · {p['params']} · {p['reason']} · pedido em {p['requested_at']}")
    print(json.dumps({"pendentes": pend}, ensure_ascii=False, default=str), flush=True)
    return 0


def _politica(a) -> int:
    """Fase 4 (Bloco 3): "esta ação seria permitida?" — pergunta à política com os fatos do estado vivo, lidos pelas
    MESMAS funções das capacidades do agente. Nunca executa nada. Código 0 permitido · 3 negado · 1 sem avaliação."""
    from agentready import capabilities, policy
    from agentready_stack import warehouse
    con = warehouse.connect(read_only=True)
    try:
        if a.acao == "adjust_campaign_budget":
            if a.novo_orcamento is None:
                print("uso: agentready-stack politica adjust_campaign_budget <campanha> <novo_orcamento>", file=sys.stderr)
                return 1
            checks = capabilities.budget_checks(con, a.campanha, float(a.novo_orcamento), a.justificativa)[0]
        else:
            checks = capabilities._common_checks(con, capabilities._campaign(con, a.campanha), a.campanha,
                                                 a.justificativa)
    finally:
        con.close()
    ev = policy.evaluator()
    print(f"Política ({ev.nome}, versão {policy.policy_version()}) · {a.acao} · {a.campanha}"
          + (f" → R$ {float(a.novo_orcamento):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
             if a.novo_orcamento is not None else ""))
    for c in checks:
        print(f"  {'✅' if c.passed else '❌'} {c.id:24s} {c.detail}")
    failed = [c.id for c in checks if not c.passed]
    if policy.FAIL_CLOSED in failed:
        print("NÃO AVALIADA: a política não respondeu — falha fechada (nenhuma ação seria executada).")
        code = 1
    elif failed:
        print(f"NEGADO ({', '.join(failed)})")
        code = 3
    else:
        print("PERMITIDO (a escada de autonomia ainda decide se executa, enfileira para aprovação ou só registra)")
        code = 0
    print(json.dumps({"acao": a.acao, "campanha": a.campanha, "novo_orcamento": a.novo_orcamento,
                      "avaliador": ev.nome, "checagens": [c.__dict__ for c in checks], "negado_por": failed},
                     ensure_ascii=False), flush=True)
    return code


def _task(a) -> int:
    if a.name == "ingest-fonte":
        return _ingest_fonte(a)
    from agentready_stack import tasks
    from agentready_stack.observe import ObservabilityAlert
    try:
        if a.name == "ingest":
            params = json.loads(a.params or os.environ.get("STACK_PARAMS") or "{}")
            out = tasks.ingest(params, a.dag_run_id)
        elif a.name == "run-agent":
            out = tasks.run_agent(a.brain, a.gullible, a.dag_run_id)
        elif a.name == "apply":
            payload = json.loads(a.payload) if a.payload else None
            out = tasks.apply_decision(a.request_id, payload, a.timeout_at)
        elif a.name == "close":
            out = tasks.close_run(a.dag_run_id)
        elif a.name == "alert":
            out = tasks.quality_alert()
        elif a.name == "observe":
            out = tasks.observe()
        elif a.name == "report":
            out = tasks.build_report()
        else:  # pragma: no cover - argparse já restringe
            raise SystemExit(f"tarefa desconhecida: {a.name}")
    except (tasks.PartialApplyError, tasks.QualityAlert, ObservabilityAlert, tasks.PolicyUnavailableError) as e:
        print(f"FALHA: {e}", file=sys.stderr)
        return 1
    except Exception as e:  # noqa: BLE001 - classifica erro de ambiente vs. falha da tarefa
        if type(e).__name__ in ("IOException", "ConnectionException") or "lock" in str(e).lower():
            return _env_error(e)
        raise
    print(tasks.dumps(out), flush=True)
    return 0


def _incident(a) -> int:
    from agentready_stack import incidents_cli, lake, tasks
    try:
        out = incidents_cli.ACTIONS[a.action]()
    except lake.RestoreRefused as e:        # Fase 4: a restauração do lake foi recusada (execução rodando, ...)
        print(f"RECUSADO: {e}", file=sys.stderr)
        return 2
    except RuntimeError as e:               # ex.: "nenhum incidente aberto"
        if "lock" in str(e).lower():
            return _env_error(e)
        print(f"FALHA: {e}", file=sys.stderr)
        return 1
    print(tasks.dumps(out), flush=True)
    return 0


def _parity(a) -> int:
    from datetime import datetime

    from rich.console import Console
    from rich.table import Table

    from agentready_stack import parity
    console = Console()
    ref = datetime.fromisoformat(a.reference_ts) if a.reference_ts else datetime.now().replace(minute=0, second=0, microsecond=0)
    scenarios = parity.ALL_SCENARIOS if a.scenario == "todos" else (a.scenario,)
    reports, ok = [], True
    for sc in scenarios:
        console.print(f"[bold]Paridade · cenário {sc}[/] (referência {ref.isoformat()}) — rodando as duas trilhas...")
        try:
            rep = parity.compare_v22(parity.run_side("default", sc, ref), parity.run_side("stack", sc, ref), sc, ref)
        except RuntimeError as e:
            if "lock" in str(e).lower():
                return _env_error(e)
            raise
        reports.append(rep)
        t = Table(title=f"{sc}: {'IGUAIS' if rep['ok'] else 'DIFERENTES'}")
        for col in ("comparação", "itens", "diferenças"):
            t.add_column(col)
        for name, label in (("campaign_daily", "Gold campanha×dia"), ("source_health", "saúde das fontes"),
                            ("decisions", "decisões do agente"), ("observability", "observabilidade (pilares)"),
                            ("traces", "trace do agente (spans)"), ("bronze", "Bronze por lote (fontes → dlt)"),
                            ("ingestion", "cargas das fontes (stack)"),
                            ("policy", "política: ações e casos (local × OPA)")):
            c = rep["compared"][name]
            t.add_row(label, str(c["items"]), "0 diferenças" if not c["diffs"] else f"[red]{len(c['diffs'])}[/]")
        console.print(t)
        for name in ("campaign_daily", "source_health", "decisions", "observability", "traces", "bronze", "ingestion",
                     "policy"):
            for d in rep["compared"][name]["diffs"][:10]:
                console.print(f"  [red]≠[/] {name} {d['key']} · {d['field']}: padrão={d['default_track']} stack={d['stack_track']}")
        ok = ok and rep["ok"]
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(reports if len(reports) > 1 else reports[0], f, ensure_ascii=False, indent=1, default=str)
    console.print("[bold green]Paridade OK: o agente decidiu igual nas duas trilhas.[/]" if ok
                  else "[bold red]Paridade FALHOU: veja as diferenças acima.[/]")
    return 0 if ok else 1


VENVS = {"dbt": "/opt/venvs/dbt/bin/python", "agente": "/opt/venvs/agent/bin/python",
         "datacontract": "/opt/venvs/dcc/bin/python", "airflow": "/home/airflow/.local/bin/python"}
PACKAGES = {"dbt": ["duckdb", "dbt-core", "dbt-duckdb", "elementary-data"], "agente": ["duckdb", "mcp", "anthropic"],
            "datacontract": ["datacontract-cli"],
            "airflow": ["apache-airflow", "astronomer-cosmos", "apache-airflow-providers-openlineage"]}
MIN_DBT = (1, 12)   # 1.11 sai do suporte em 18/12/2026; 1.12 tem suporte ativo até 15/07/2027 (pesquisa R1, Fase 2)


def _versions(python: str, packages: list[str]) -> dict:
    import subprocess
    code = ("import json, importlib.metadata as m, sys\n"
            "out = {}\n"
            "for p in sys.argv[1:]:\n"
            "    try: out[p] = m.version(p)\n"
            "    except m.PackageNotFoundError: out[p] = None\n"
            "print(json.dumps(out))")
    r = subprocess.run([python, "-c", code, *packages], capture_output=True, text=True)
    return json.loads(r.stdout) if r.returncode == 0 else {p: None for p in packages}


def _doctor(_a) -> int:
    """Versões de cada ambiente e a única regra que quebra o warehouse: o DuckDB de quem abre o arquivo."""
    found, missing = {}, []
    for venv, python in VENVS.items():
        if not os.path.exists(python):
            missing.append(venv)
            continue
        found[venv] = _versions(python, PACKAGES[venv])
        print(f"{venv:13s} " + " · ".join(f"{p} {v or 'AUSENTE'}" for p, v in found[venv].items()))
    if missing:
        print(f"ERRO de ambiente: venvs não encontrados: {', '.join(missing)} (rode dentro do container)", file=sys.stderr)
        return 2
    absent = [f"{v}:{p}" for v, pk in found.items() for p, ver in pk.items() if ver is None]
    duck = {v: found[v]["duckdb"] for v in ("dbt", "agente")}
    if len(set(duck.values())) != 1:
        print(f"FALHA: o DuckDB difere entre os ambientes que abrem o warehouse {duck}. "
              "O arquivo só abre com a mesma versão de formato.", file=sys.stderr)
        return 1
    if absent:
        print(f"FALHA: pacotes ausentes: {', '.join(absent)}", file=sys.stderr)
        return 1
    print(f"ok: DuckDB {duck['dbt']} igual nos ambientes que abrem o warehouse (dbt e agente); "
          "o datacontract-cli não abre o warehouse.")
    # Fase 4: o venv da ingestão (dlt) também abre o ops.duckdb e o lake; e as extensões vêm da imagem (offline).
    import subprocess
    ingest_py = "/opt/venvs/ingest/bin/python"
    if os.path.exists(ingest_py):
        ing = _versions(ingest_py, ["duckdb", "dlt", "pyarrow"])
        print(f"{'ingestao':13s} " + " · ".join(f"{p} {v or 'AUSENTE'}" for p, v in ing.items()))
        if ing.get("duckdb") != duck["dbt"]:
            print(f"FALHA: o DuckDB do venv da ingestão ({ing.get('duckdb')}) difere do resto ({duck['dbt']}).",
                  file=sys.stderr)
            return 1
        ext = os.environ.get("STACK_DUCKDB_EXTENSIONS", "/opt/duckdb-extensions")
        r = subprocess.run([VENVS["agente"], "-c", "import duckdb,sys; c=duckdb.connect(); "
                            f"c.execute(\"SET extension_directory='{ext}'\"); "
                            "print(', '.join(f'{n} {v}' for n, v in c.execute(\"SELECT extension_name, extension_version "
                            "FROM duckdb_extensions() WHERE installed AND extension_name IN ('ducklake','postgres_scanner')\""
                            ").fetchall()))"], capture_output=True, text=True)
        print(f"ok: extensões do DuckDB na imagem (offline): {r.stdout.strip() or 'NENHUMA — reconstrua a imagem'}")
    dbt_minor = tuple(int(x) for x in found["dbt"]["dbt-core"].split(".")[:2])
    if dbt_minor < MIN_DBT:
        print(f"AVISO: dbt-core {found['dbt']['dbt-core']} está fora do suporte ativo da dbt Labs; "
              f"a trilha usa {MIN_DBT[0]}.{MIN_DBT[1]}.x (suporte ativo até jul/2027).")
    else:
        print(f"ok: dbt-core {found['dbt']['dbt-core']} em versão com suporte ativo.")
    from agentready_stack import lineage
    lin = lineage.check()
    print(f"ok: linhagem — Marquez respondendo em {lin['url']}" if lin["ok"]
          else f"AVISO: linhagem indisponível ({lin['reason']}). A execução segue; só fica sem registro no Marquez.")
    return 0


def main(argv: list[str] | None = None) -> int:
    from agentready_stack import telemetry
    telemetry.attach_from_env()
    try:
        return _main(argv)
    finally:
        telemetry.flush()


def _main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="agentready-stack", description="Trilha stack do workshop agentready")
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("task", help="roda uma etapa do DAG")
    t.add_argument("name", choices=["ingest", "ingest-fonte", "run-agent", "apply", "close", "alert", "observe",
                                    "report"])
    t.add_argument("fonte", nargs="?", choices=["ads", "ga4", "meta_capi", "catalogo"],
                   help="só para ingest-fonte (Fase 4)")
    t.add_argument("--params", help="JSON com os parâmetros da execução (ou variável STACK_PARAMS)")
    t.add_argument("--brain", default="rules", choices=["rules", "claude"])
    t.add_argument("--gullible", action="store_true")
    t.add_argument("--dag-run-id")
    t.add_argument("--request-id")
    t.add_argument("--payload", help="JSON devolvido pela tarefa HITL (vazio = sem resposta)")
    t.add_argument("--timeout-at")
    p = sub.add_parser("parity", help="compara trilha padrão × trilha stack (Gold, fontes, decisões)")
    p.add_argument("--scenario", default="todos", choices=["manha", "pos_backfill", "supervisionado",
                                                           "incidente_centavos", "incidente_renomeacao",
                                                           "incidente_lote_duplicado", "incidente_feed_parado", "todos"])
    p.add_argument("--reference-ts", help="horário de referência ISO (padrão: a hora cheia atual)")
    p.add_argument("--json", help="grava o relatório (parity-report.schema.json) neste arquivo")
    sub.add_parser("doctor", help="versões de cada ambiente e compatibilidade do DuckDB")
    inc = sub.add_parser("incident", help="Bloco 5: detect | resolve | reveal | list (warehouse da stack)")
    inc.add_argument("action", choices=["detect", "resolve", "reveal", "list"])
    dec = sub.add_parser("decisions", help="decisões do agente desde um horário (FR-012)")
    dec.add_argument("--since", default="", help="vazio = desde o último incidente · HH:MM = hoje · ISO")
    sub.add_parser("lineage-check", help="o Marquez responde? (nunca falha: só avisa)")
    rb = sub.add_parser("rollback", help="Fase 3: desfaz uma alteração do agente, ligada ao trace da decisão")
    rb.add_argument("change_id")
    rb.add_argument("--by", default="instrutor")
    sub.add_parser("fontes", help="Fase 4: a última carga de cada fonte simulada")
    sub.add_parser("approvals", help="pedidos aguardando aprovação humana (lê o ops.duckdb da stack)")
    po = sub.add_parser("politica", help="Fase 4: pergunta à política se uma ação seria permitida (não executa)")
    po.add_argument("acao", choices=["adjust_campaign_budget", "pause_campaign"])
    po.add_argument("campanha")
    po.add_argument("novo_orcamento", nargs="?")
    po.add_argument("--justificativa", default="consulta do instrutor (make politica)")
    sn = sub.add_parser("snapshots", help="Fase 4: marcos do lake (snapshots com nome)")
    sn.add_argument("--limit", type=int, default=30)
    ce = sub.add_parser("consultar-em", help="Fase 4: uma tabela das camadas de dados num snapshot ou horário")
    ce.add_argument("tabela")
    ce.add_argument("em", help="número do snapshot ou AAAA-MM-DDTHH:MM")
    ce.add_argument("--filtro")
    ce.add_argument("--limite", type=int, default=20)
    ge = sub.add_parser("gold-em", help="Fase 4: a Gold que o agente leu para uma decisão (trace, CHG-… ou REQ-…)")
    ge.add_argument("decisao")
    rs = sub.add_parser("restaurar", help="Fase 4: volta as camadas de dados a um snapshot (vira um snapshot novo)")
    rs.add_argument("para", help="número do snapshot ou marco CK-…")
    rs.add_argument("--motivo")
    rs.add_argument("--por", default="instrutor")
    tr = sub.add_parser("traces", help="Fase 3: últimas execuções com o link do trace no Phoenix")
    tr.add_argument("--limit", type=int, default=10)
    a = ap.parse_args(argv)
    if a.cmd == "rollback":
        from agentready_stack import rollback, tasks
        try:
            print(tasks.dumps(rollback.run(a.change_id, a.by)), flush=True)
        except ValueError as e:
            print(f"FALHA: {e}", file=sys.stderr)
            return 1
        return 0
    if a.cmd == "fontes":
        return _fontes()
    if a.cmd == "approvals":
        return _approvals()
    if a.cmd == "politica":
        return _politica(a)
    if a.cmd in ("snapshots", "consultar-em", "gold-em", "restaurar"):
        return _lake_cmd(a)
    if a.cmd == "traces":
        from agentready_stack import incidents_cli, tasks
        print(tasks.dumps(incidents_cli.traces(a.limit)), flush=True)
        return 0
    if a.cmd == "decisions":
        from agentready_stack import incidents_cli, tasks
        try:
            print(tasks.dumps(incidents_cli.decisions_since(a.since)), flush=True)
        except ValueError as e:
            print(f"FALHA: {e}", file=sys.stderr)
            return 1
        return 0
    if a.cmd == "lineage-check":
        from agentready_stack import lineage, tasks
        r = lineage.check()
        print("Linhagem: Marquez respondendo em " + r["url"] if r["ok"] else f"linhagem indisponível: {r['reason']}")
        print(tasks.dumps(r), flush=True)
        return 0
    if a.cmd == "doctor":
        return _doctor(a)
    if a.cmd == "incident":
        return _incident(a)
    if a.cmd == "task":
        return _task(a)
    if a.cmd == "parity":
        return _parity(a)
    return 0


if __name__ == "__main__":
    sys.exit(main())
