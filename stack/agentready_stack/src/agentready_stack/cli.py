"""CLI `agentready-stack`: as mesmas tarefas que o DAG roda, executáveis à mão.

  agentready-stack task ingest      [--params JSON]
  agentready-stack task run-agent   [--brain rules|claude] [--gullible] [--dag-run-id ID]
  agentready-stack task apply       --request-id REQ [--payload JSON] [--timeout-at ISO]
  agentready-stack task close       [--dag-run-id ID]
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
        else:  # pragma: no cover - argparse já restringe
            raise SystemExit(f"tarefa desconhecida: {a.name}")
    except tasks.PartialApplyError as e:
        print(f"FALHA: {e}", file=sys.stderr)
        return 1
    except Exception as e:  # noqa: BLE001 - classifica erro de ambiente vs. falha da tarefa
        if type(e).__name__ in ("IOException", "ConnectionException") or "lock" in str(e).lower():
            return _env_error(e)
        raise
    print(tasks.dumps(out), flush=True)
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="agentready-stack", description="Trilha stack do workshop agentready")
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("task", help="roda uma etapa do DAG")
    t.add_argument("name", choices=["ingest", "run-agent", "apply", "close"])
    t.add_argument("--params", help="JSON com os parâmetros da execução (ou variável STACK_PARAMS)")
    t.add_argument("--brain", default="rules", choices=["rules", "claude"])
    t.add_argument("--gullible", action="store_true")
    t.add_argument("--dag-run-id")
    t.add_argument("--request-id")
    t.add_argument("--payload", help="JSON devolvido pela tarefa HITL (vazio = sem resposta)")
    t.add_argument("--timeout-at")
    a = ap.parse_args(argv)
    if a.cmd == "task":
        return _task(a)
    return 0


if __name__ == "__main__":
    sys.exit(main())
