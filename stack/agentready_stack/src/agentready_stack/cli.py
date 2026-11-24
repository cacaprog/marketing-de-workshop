"""CLI `agentready-stack`: as mesmas tarefas que o DAG roda, executáveis à mão.

  agentready-stack task ingest      [--params JSON]
  agentready-stack task run-agent   [--brain rules|claude] [--gullible] [--dag-run-id ID]
  agentready-stack task apply       --request-id REQ [--payload JSON] [--timeout-at ISO]
  agentready-stack task close       [--dag-run-id ID]
  agentready-stack task alert
  agentready-stack parity           --scenario manha|pos_backfill|supervisionado|todos  (US2)
  agentready-stack doctor                                                             (polimento)

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


def _task(a) -> int:
    from agentready_stack import tasks
    try:
        if a.name == "ingest":
            params = json.loads(a.params or os.environ.get("STACK_PARAMS") or "{}")
            out = tasks.ingest(params)
        elif a.name == "run-agent":
            out = tasks.run_agent(a.brain, a.gullible, a.dag_run_id)
        elif a.name == "apply":
            payload = json.loads(a.payload) if a.payload else None
            out = tasks.apply_decision(a.request_id, payload, a.timeout_at)
        elif a.name == "close":
            out = tasks.close_run(a.dag_run_id)
        elif a.name == "alert":
            out = tasks.quality_alert()
        else:  # pragma: no cover - argparse já restringe
            raise SystemExit(f"tarefa desconhecida: {a.name}")
    except (tasks.PartialApplyError, tasks.QualityAlert) as e:
        print(f"FALHA: {e}", file=sys.stderr)
        return 1
    except Exception as e:  # noqa: BLE001 - classifica erro de ambiente vs. falha da tarefa
        if type(e).__name__ in ("IOException", "ConnectionException") or "lock" in str(e).lower():
            return _env_error(e)
        raise
    print(tasks.dumps(out), flush=True)
    return 0


def _parity(a) -> int:
    from datetime import datetime

    from rich.console import Console
    from rich.table import Table

    from agentready_stack import parity
    console = Console()
    ref = datetime.fromisoformat(a.reference_ts) if a.reference_ts else datetime.now().replace(minute=0, second=0, microsecond=0)
    scenarios = parity.SCENARIOS if a.scenario == "todos" else (a.scenario,)
    reports, ok = [], True
    for sc in scenarios:
        console.print(f"[bold]Paridade · cenário {sc}[/] (referência {ref.isoformat()}) — rodando as duas trilhas...")
        try:
            rep = parity.compare(parity.run_side("default", sc, ref), parity.run_side("stack", sc, ref), sc, ref)
        except RuntimeError as e:
            if "lock" in str(e).lower():
                return _env_error(e)
            raise
        reports.append(rep)
        t = Table(title=f"{sc}: {'IGUAIS' if rep['ok'] else 'DIFERENTES'}")
        for col in ("comparação", "itens", "diferenças"):
            t.add_column(col)
        for name, label in (("campaign_daily", "Gold campanha×dia"), ("source_health", "saúde das fontes"),
                            ("decisions", "decisões do agente")):
            c = rep["compared"][name]
            t.add_row(label, str(c["items"]), "0 diferenças" if not c["diffs"] else f"[red]{len(c['diffs'])}[/]")
        console.print(t)
        for name in ("campaign_daily", "source_health", "decisions"):
            for d in rep["compared"][name]["diffs"][:10]:
                console.print(f"  [red]≠[/] {name} {d['key']} · {d['field']}: padrão={d['default_track']} stack={d['stack_track']}")
        ok = ok and rep["ok"]
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(reports if len(reports) > 1 else reports[0], f, ensure_ascii=False, indent=1, default=str)
    console.print("[bold green]Paridade OK: o agente decidiu igual nas duas trilhas.[/]" if ok
                  else "[bold red]Paridade FALHOU: veja as diferenças acima.[/]")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="agentready-stack", description="Trilha stack do workshop agentready")
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("task", help="roda uma etapa do DAG")
    t.add_argument("name", choices=["ingest", "run-agent", "apply", "close", "alert"])
    t.add_argument("--params", help="JSON com os parâmetros da execução (ou variável STACK_PARAMS)")
    t.add_argument("--brain", default="rules", choices=["rules", "claude"])
    t.add_argument("--gullible", action="store_true")
    t.add_argument("--dag-run-id")
    t.add_argument("--request-id")
    t.add_argument("--payload", help="JSON devolvido pela tarefa HITL (vazio = sem resposta)")
    t.add_argument("--timeout-at")
    p = sub.add_parser("parity", help="compara trilha padrão × trilha stack (Gold, fontes, decisões)")
    p.add_argument("--scenario", default="todos", choices=["manha", "pos_backfill", "supervisionado", "todos"])
    p.add_argument("--reference-ts", help="horário de referência ISO (padrão: a hora cheia atual)")
    p.add_argument("--json", help="grava o relatório (parity-report.schema.json) neste arquivo")
    a = ap.parse_args(argv)
    if a.cmd == "task":
        return _task(a)
    if a.cmd == "parity":
        return _parity(a)
    return 0


if __name__ == "__main__":
    sys.exit(main())
