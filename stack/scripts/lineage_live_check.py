#!/usr/bin/env python3
"""`make test-live` (Fase 2, US3): linhagem de verdade, com a stack no ar.

1. Execução A (Marquez no ar)        → roda tests/test_lineage.py contra ela.
2. Execução B com o Marquez PARADO   → mesmos estados de tarefa e mesmas decisões que A, e o aviso
                                        "linhagem indisponível" no fechamento (FR-013).
3. Execução C (Marquez de volta)     → reexecução cria novas RUNS dos mesmos jobs, nunca jobs novos.

As três rodam com autonomia `shadow` (o agente registra, não executa nem enfileira): nenhuma espera
aprovação humana. No fim o override de autonomia é limpo. Roda no HOST (usa docker compose e a API).
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

STACK = Path(__file__).resolve().parents[1]
API = "http://localhost:" + next((l.split("=", 1)[1].strip() for l in (STACK / ".env").read_text().splitlines()
                                  if l.startswith("AIRFLOW_PORT=")), "8080")
DAG = "aurora_midia_diario"
CONF = {"reset_scenario": True, "autonomy_override": "shadow"}
IGNORED_STATES = {"removed", None}
# O alerta de qualidade depende do HISTÓRICO (só acende com lote barrado NOVO desde a marca d'água da última
# execução bem-sucedida), então duas execuções seguidas diferem nele por desenho, com ou sem Marquez.
HISTORY_DEPENDENT = {"contratos.alerta_qualidade"}


def say(t: str) -> None:
    print(t, flush=True)


def token() -> str:
    pw = json.loads((STACK / "config" / "passwords.json").read_text())["instrutor"]
    req = urllib.request.Request(f"{API}/auth/token", data=json.dumps({"username": "instrutor", "password": pw}).encode(),
                                 headers={"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=10))["access_token"]


def api(path: str, body: dict | None = None):
    req = urllib.request.Request(f"{API}/api/v2{path}", data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": f"Bearer {token()}", "Content-Type": "application/json"},
                                 method="POST" if body is not None else "GET")
    return json.load(urllib.request.urlopen(req, timeout=30))


def compose(*args: str) -> None:
    subprocess.run(["docker", "compose", *args], cwd=STACK, check=True, capture_output=True)


def in_container(cmd: str) -> subprocess.CompletedProcess:
    return subprocess.run(["docker", "compose", "run", "--rm", "--no-deps", "airflow-scheduler", "bash", "-c", cmd],
                          cwd=STACK, capture_output=True, text=True)


def run_and_wait(label: str) -> dict:
    run_id = api(f"/dags/{DAG}/dagRuns", {"logical_date": None, "conf": CONF})["dag_run_id"]
    enc = urllib.parse.quote(run_id, safe="")
    t0 = time.time()
    while True:
        time.sleep(5)
        state = api(f"/dags/{DAG}/dagRuns/{enc}")["state"]
        if state not in ("queued", "running"):
            break
        if time.time() - t0 > 900:
            raise SystemExit(f"ERRO: a execução {label} passou de 15 min")
    tis = api(f"/dags/{DAG}/dagRuns/{enc}/taskInstances?limit=500")["task_instances"]
    states = {(t["task_id"], t["map_index"]): t["state"] for t in tis
              if t["state"] not in IGNORED_STATES and t["task_id"] not in HISTORY_DEPENDENT}
    agent = api(f"/dags/{DAG}/dagRuns/{enc}/taskInstances/agente.executar/xcomEntries/return_value")["value"]
    close = api(f"/dags/{DAG}/dagRuns/{enc}/taskInstances/fechamento.marca_d_agua/xcomEntries/return_value")["value"]
    agent = json.loads(agent) if isinstance(agent, str) else agent
    close = json.loads(close) if isinstance(close, str) else close
    secs = int(time.time() - t0)
    say(f"  execução {label}: {run_id} · {state} · {secs} s")
    return {"run_id": run_id, "state": state, "secs": secs, "states": states, "close": close,
            "decisions": [s["text"] for s in agent.get("steps", []) if s["kind"] in ("action", "refusal")]}


def marquez_counts() -> tuple[int, int]:
    r = in_container("curl -sf 'http://marquez-api:5000/api/v1/namespaces/aurora/jobs?limit=500' | python3 -c "
                     "'import json,sys;js=json.load(sys.stdin)[\"jobs\"];print(len(js))'; "
                     "curl -sf 'http://marquez-api:5000/api/v1/namespaces/aurora/jobs/"
                     "aurora_midia_diario.agente.executar/runs?limit=500' | python3 -c "
                     "'import json,sys;print(len(json.load(sys.stdin)[\"runs\"]))'")
    jobs, runs = r.stdout.split()[-2:]
    return int(jobs), int(runs)


def main() -> int:
    failures = []
    say("Linhagem ao vivo (3 execuções em modo shadow; nenhuma espera aprovação)")
    a = run_and_wait("A (Marquez no ar)")
    say("  testes de linhagem contra a execução A...")
    t = in_container("PYTHONDONTWRITEBYTECODE=1 /opt/venvs/agent/bin/pytest /opt/agentready/stack/tests/test_lineage.py "
                     "-q -p no:cacheprovider 2>&1 | tail -15")
    say("  " + t.stdout.strip().replace("\n", "\n  "))
    if " failed" in t.stdout or "error" in t.stdout.lower().split("passed")[-1]:
        failures.append("tests/test_lineage.py")
    jobs1, runs1 = marquez_counts()

    say("  parando o Marquez (marquez-api) para a execução B...")
    compose("stop", "marquez-api")
    try:
        b = run_and_wait("B (Marquez PARADO)")
    finally:
        compose("start", "marquez-api")
        say("  Marquez de volta (marquez-api iniciado)")
    if b["states"] != a["states"]:
        diff = {k: (a["states"].get(k), b["states"].get(k)) for k in set(a["states"]) | set(b["states"])
                if a["states"].get(k) != b["states"].get(k)}
        failures.append(f"estados de tarefa diferentes sem o Marquez: {diff}")
    if b["decisions"] != a["decisions"]:
        failures.append("decisões do agente diferentes sem o Marquez")
    if b["secs"] > max(300, 1.5 * a["secs"]):
        failures.append(f"sem o Marquez a execução ficou lenta demais ({a['secs']} s → {b['secs']} s)")
    if "linhagem indisponível" not in b["close"]["summary"]:
        failures.append("o fechamento da execução B não registrou 'linhagem indisponível'")

    for _ in range(36):                                   # espera o Marquez ficar saudável de novo
        if in_container("curl -sf http://marquez-api:5000/api/v1/namespaces >/dev/null").returncode == 0:
            break
        time.sleep(5)
    run_and_wait("C (reexecução, Marquez no ar)")
    jobs2, runs2 = marquez_counts()
    if jobs2 != jobs1:
        failures.append(f"a reexecução criou jobs novos no Marquez ({jobs1} → {jobs2})")
    if runs2 <= runs1:
        failures.append(f"a reexecução não criou nova run do agente ({runs1} → {runs2})")

    in_container("/opt/venvs/agent/bin/python -c 'from agentready import autonomy; from agentready.db import connect; "
                 "c=connect(); autonomy.set_override(c, None); c.close()'")
    say("  override de autonomia limpo")
    if failures:
        say("FALHOU:\n  - " + "\n  - ".join(failures))
        return 1
    say(f"OK: linhagem completa; execução sem o Marquez igual à com Marquez; reexecução = novas runs "
        f"({jobs1} jobs, runs do agente {runs1} → {runs2}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
