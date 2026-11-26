#!/usr/bin/env python3
"""`make test-live` (Fases 2 e 3): linhagem e traces de verdade, com a stack no ar.

Fase 2 (linhagem, US3 da spec 002):
1. Execução A (Marquez no ar)        → roda tests/test_lineage.py contra ela.
2. Execução B com o Marquez PARADO   → mesmos estados de tarefa e mesmas decisões que A, e o aviso
                                        "linhagem indisponível" no fechamento (FR-013).
3. Execução C (Marquez de volta)     → reexecução cria novas RUNS dos mesmos jobs, nunca jobs novos.

Fase 3 (traces, spec 003, T038):
a. Execução A: a cópia do trace do agente no Phoenix é igual à do log de auditoria; SC-004 (o trace do
   agente aparece no Phoenix ≤ 30 s depois do fim da tarefa do agente).
b. Execução D: o Phoenix PARA no meio → mesmo estado de A, aviso "fila do coletor" no fechamento,
   log de auditoria íntegro; com o Phoenix de volta, o trace chega (fila esvaziada).
c. Execução E: o COLETOR parado a execução inteira → mesmo estado de A, no máximo +60 s, aviso
   "coletor fora do ar", e as decisões de E estão no log de auditoria.
f. Execução F: um passo da observabilidade falha → o agente não roda (upstream_failed), o span raiz
   da execução termina em ERROR e o trace não tem `agent.run`.
e. FR-003: depois de `down` + `make up` (sem reset), o trace de A continua lá e o filtro por data de
   negócio e por execução o encontra.

Todas rodam com autonomia `shadow` (o agente registra, não executa nem enfileira): nenhuma espera
aprovação humana. No fim o override de autonomia é limpo. Roda no HOST (usa docker compose e as APIs).
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

STACK = Path(__file__).resolve().parents[1]
API = "http://localhost:" + next((l.split("=", 1)[1].strip() for l in (STACK / ".env").read_text().splitlines()
                                  if l.startswith("AIRFLOW_PORT=")), "8080")
PHOENIX = "http://localhost:" + next((l.split("=", 1)[1].strip() for l in (STACK / ".env").read_text().splitlines()
                                      if l.startswith("PHOENIX_PORT=")), "6006")
DAG = "aurora_midia_diario"
NS = "aurora"                       # namespace OpenLineage do Airflow (AIRFLOW__OPENLINEAGE__NAMESPACE)
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


def run_and_wait(label: str, on_agent=None, after_trigger=None, allow_missing_xcom: bool = False) -> dict:
    """`on_agent(enc_run_id, ti)` é chamado UMA vez, quando agente.executar começa ou termina;
    `after_trigger(enc_run_id)` logo depois de disparar (Fase 3)."""
    run_id = api(f"/dags/{DAG}/dagRuns", {"logical_date": None, "conf": CONF})["dag_run_id"]
    enc = urllib.parse.quote(run_id, safe="")
    if after_trigger:
        after_trigger(enc)
    t0 = time.time()
    hooked = on_agent is None
    while True:
        time.sleep(5)
        state = api(f"/dags/{DAG}/dagRuns/{enc}")["state"]
        if not hooked:
            ti = api(f"/dags/{DAG}/dagRuns/{enc}/taskInstances/agente.executar")
            if ti["state"] in ("running", "success", "failed"):
                hooked = True
                on_agent(enc, ti)
        if state not in ("queued", "running"):
            break
        if time.time() - t0 > 900:
            raise SystemExit(f"ERRO: a execução {label} passou de 15 min")
    tis = api(f"/dags/{DAG}/dagRuns/{enc}/taskInstances?limit=500")["task_instances"]
    states = {(t["task_id"], t["map_index"]): t["state"] for t in tis
              if t["state"] not in IGNORED_STATES and t["task_id"] not in HISTORY_DEPENDENT}
    # Só a execução F (agente não alcançado) pode não ter XCom: nas outras, faltar é defeito, não "lista vazia".
    agent = xcom(enc, "agente.executar", allow_missing_xcom)
    close = xcom(enc, "fechamento.marca_d_agua", allow_missing_xcom)
    prep = xcom(enc, "ingestao.preparar", allow_missing_xcom)
    secs = int(time.time() - t0)
    say(f"  execução {label}: {run_id} · {state} · {secs} s")
    return {"run_id": run_id, "state": state, "secs": secs, "states": states, "close": close, "agent": agent,
            "trace_id": agent.get("trace_id"),
            # data de negócio = a do horário de referência da execução (America/Sao_Paulo no container)
            "business_date": (prep.get("reference_ts") or "")[:10] or None,
            "decisions": [s["text"] for s in agent.get("steps", []) if s["kind"] in ("action", "refusal")]}


def xcom(enc: str, task_id: str, allow_missing: bool = False) -> dict:
    try:
        v = api(f"/dags/{DAG}/dagRuns/{enc}/taskInstances/{task_id}/xcomEntries/return_value")["value"]
    except urllib.error.HTTPError:
        if allow_missing:
            return {}
        raise SystemExit(f"ERRO: a tarefa {task_id} não deixou resultado (XCom) na execução {enc}")
    return (json.loads(v) if isinstance(v, str) else v) or {}


# ------------------------------------------------------------------ Fase 3: Phoenix

def gql(query: str, variables: dict | None = None) -> dict:
    req = urllib.request.Request(f"{PHOENIX}/graphql", data=json.dumps({"query": query, "variables": variables or {}}).encode(),
                                 headers={"Content-Type": "application/json"})
    body = json.load(urllib.request.urlopen(req, timeout=10))
    if body.get("errors"):
        raise RuntimeError(body["errors"][0].get("message"))
    return body["data"]


def phoenix_trace_names(trace_id: str) -> list[str] | None:
    """Nomes dos spans do trace no Phoenix (None se o trace não está lá ou o Phoenix não responde)."""
    try:
        t = gql("query($t: String!){ getTraceByOtelId(traceId:$t){ spans(first: 1000){ edges { node { name statusCode "
                "parentId } } } } }", {"t": trace_id})["getTraceByOtelId"]
    except Exception:  # noqa: BLE001
        return None
    return [e["node"]["name"] + ("!" if e["node"]["statusCode"] == "ERROR" and e["node"]["parentId"] is None else "")
            for e in t["spans"]["edges"]] if t else None


def wait_for_phoenix_trace(trace_id: str, timeout: float, need: str = "agent.run") -> float | None:
    """Segundos até o span `need` do trace aparecer no Phoenix (None se não apareceu no prazo)."""
    t0 = time.time()
    while time.time() - t0 < timeout:
        names = phoenix_trace_names(trace_id) or []
        if need in names:
            return time.time() - t0
        time.sleep(2)
    return None


def project_id() -> str:
    for e in gql("{ projects { edges { node { id name } } } }")["projects"]["edges"]:
        if e["node"]["name"] == "aurora":
            return e["node"]["id"]
    raise RuntimeError("projeto 'aurora' não existe no Phoenix")


def phoenix_filter(condition: str) -> set[str]:
    """trace_ids dos spans que atendem ao filtro do Phoenix (sintaxe de atributo aninhado)."""
    d = gql("query($p: ID!, $f: String!){ node(id:$p){ ... on Project { spans(first: 1000, filterCondition: $f) "
            "{ edges { node { context { traceId } } } } } } }", {"p": project_id(), "f": condition})
    return {e["node"]["context"]["traceId"] for e in d["node"]["spans"]["edges"]}


def audit_has_agent_run(trace_id: str) -> bool:
    r = in_container(f"/opt/venvs/agent/bin/python -c 'from agentready import tracing; "
                     f"print(any(x[\"name\"] == \"agent.run\" for x in tracing.load(\"{trace_id}\")))'")
    return r.stdout.strip().endswith("True")


def verify_chain_ok() -> bool:
    return in_container("/opt/venvs/agent/bin/agentready verify").returncode == 0


def phase3(a: dict, failures: list[str]) -> None:
    """Fase 3 (T038). `a` é a execução A (Phoenix e coletor no ar)."""
    say("Traces ao vivo (Fase 3)")
    # (a) cópia do Phoenix == cópia do log de auditoria
    r = in_container(f"/opt/venvs/agent/bin/python -m agentready_stack.trace_check {a['trace_id']}")
    res = json.loads(r.stdout.strip().splitlines()[-1]) if r.stdout.strip() else {"ok": False, "diffs": [r.stderr[-300:]]}
    say(f"  (a) Phoenix × log de auditoria, execução A: {res.get('phoenix_spans')} × {res.get('audit_spans')} spans, "
        f"{len(res['diffs'])} diferença(s)")
    if not res["ok"]:
        failures.append(f"trace do agente diferente no Phoenix: {res['diffs'][:3]}")
    if a.get("sc004") is None:
        failures.append("SC-004: o trace do agente da execução A não apareceu no Phoenix em 60 s")
    elif a["sc004"] > 30:
        failures.append(f"SC-004: o trace levou {a['sc004']:.0f} s (> 30 s) para aparecer no Phoenix")

    # (b) Phoenix para no meio da execução
    stopped = {}

    def stop_phoenix(enc, ti):
        compose("stop", "phoenix")
        stopped["at"] = time.time()
        say("  Phoenix PARADO (agente.executar em andamento)")
    try:
        d = run_and_wait("D (Phoenix parado no meio)", on_agent=stop_phoenix)
    finally:
        compose("start", "phoenix")
        say("  Phoenix de volta (phoenix iniciado)")
    if d["states"] != a["states"]:
        failures.append("estados de tarefa diferentes com o Phoenix parado")
    reason = (d["close"].get("traces") or {}).get("reason") or ""
    if "fila do coletor" not in reason:
        failures.append(f"o fechamento da execução D não avisou da fila do coletor (motivo: {reason!r})")
    if not verify_chain_ok():
        failures.append("log de auditoria não íntegro depois da execução D")
    gap = wait_for_phoenix_trace(d["trace_id"], 120)
    say(f"  (b) fila do coletor esvaziada: trace de D no Phoenix " + (f"após {gap:.0f} s" if gap is not None else "NÃO chegou"))
    if gap is None:
        failures.append("a fila do coletor não entregou o trace da execução D em 2 min")

    # (c) coletor parado a execução inteira
    compose("stop", "otel-collector")
    say("  coletor PARADO para a execução E")
    try:
        e = run_and_wait("E (coletor parado)")
    finally:
        compose("start", "otel-collector")
        say("  coletor de volta")
    if e["states"] != a["states"]:
        failures.append("estados de tarefa diferentes com o coletor parado")
    if e["secs"] > a["secs"] + 60:
        failures.append(f"sem o coletor a execução ficou lenta demais ({a['secs']} s → {e['secs']} s)")
    reason = (e["close"].get("traces") or {}).get("reason") or ""
    if not reason.startswith("coletor fora do ar"):
        failures.append(f"o fechamento da execução E não avisou 'coletor fora do ar' (motivo: {reason!r})")
    if not (e["trace_id"] and audit_has_agent_run(e["trace_id"])):
        failures.append("as decisões da execução E não estão no log de auditoria")
    say(f"  (c) sem coletor: {a['secs']} s → {e['secs']} s; decisões no log de auditoria: "
        f"{'sim' if e['trace_id'] and audit_has_agent_run(e['trace_id']) else 'NÃO'}")

    # (f) agente não alcançado
    def fail_obs(enc):
        api_patch(f"/dags/{DAG}/dagRuns/{enc}/taskInstances/observabilidade.verificar.obs_volume_run",
                  {"new_state": "failed"})
    f = run_and_wait("F (um passo da observabilidade falha)", after_trigger=fail_obs, allow_missing_xcom=True)
    agent_state = f["states"].get(("agente.executar", -1))
    names = None
    for _ in range(12):                    # a ingestão no Phoenix e o span raiz podem chegar alguns segundos depois
        traces_f = phoenix_filter(f'attributes["airflow"]["dag_run"]["run_id"] == "{f["run_id"]}"')
        names = phoenix_trace_names(next(iter(traces_f))) if traces_f else None
        if names and "dag_run.aurora_midia_diario!" in names:
            break
        time.sleep(5)
    say(f"  (f) agente.executar = {agent_state}; raiz em ERROR: {bool(names and 'dag_run.aurora_midia_diario!' in names)}; "
        f"agent.run no trace: {bool(names and 'agent.run' in names)}")
    if agent_state != "upstream_failed":
        failures.append(f"execução F: agente.executar deveria ser upstream_failed, foi {agent_state}")
    if not names or "dag_run.aurora_midia_diario!" not in names or "agent.run" in names:
        failures.append("execução F: o trace deveria ter a raiz em ERROR e nenhum agent.run")

    # (e) FR-003: persistência e busca
    say("  (e) down + up (sem reset)...")
    compose("down")
    subprocess.run(["make", "up"], cwd=STACK, check=True, capture_output=True)
    # A data de negócio vem da própria execução A (não do relógio do host); o filtro por data se restringe a
    # agente.resultado (um span por execução), para o limite de 1000 spans da consulta nunca cortar o trace de A.
    business_date = a["business_date"]
    by_run = phoenix_filter(f'attributes["airflow"]["dag_run"]["run_id"] == "{a["run_id"]}"')
    by_date = phoenix_filter(f'attributes["agentready"]["business_date"] == "{business_date}" '
                             f'and name == "agente.resultado"')
    still = phoenix_trace_names(a["trace_id"]) is not None
    say(f"  (e) trace de A depois de reiniciar: {'presente' if still else 'AUSENTE'}; filtro por execução: "
        f"{a['trace_id'] in by_run}; filtro por data de negócio: {a['trace_id'] in by_date}")
    if not (still and a["trace_id"] in by_run and a["trace_id"] in by_date):
        failures.append("FR-003: o trace de A não sobreviveu ao reinício ou o filtro não o encontrou")


def api_patch(path: str, body: dict) -> dict:
    req = urllib.request.Request(f"{API}/api/v2{path}", data=json.dumps(body).encode(), method="PATCH",
                                 headers={"Authorization": f"Bearer {token()}", "Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=30))


def marquez_counts() -> tuple[int, int]:
    r = in_container("curl -sf 'http://marquez-api:5000/api/v1/namespaces/aurora/jobs?limit=500' | python3 -c "
                     "'import json,sys;js=json.load(sys.stdin)[\"jobs\"];print(len(js))'; "
                     "curl -sf 'http://marquez-api:5000/api/v1/namespaces/aurora/jobs/"
                     "aurora_midia_diario.agente.executar/runs?limit=500' | python3 -c "
                     "'import json,sys;print(len(json.load(sys.stdin)[\"runs\"]))'")
    jobs, runs = r.stdout.split()[-2:]
    return int(jobs), int(runs)


FONTES = {"ads": ("fonte://ads", "investimento"), "ga4": ("fonte://ga4", "conversoes"),
          "meta_capi": ("fonte://meta", "conversoes"), "catalogo": ("fonte://catalogo", "campanhas")}


def phase4_sources(failures: list[str]) -> None:
    """Fase 4 (FR-007): cada fonte simulada é um nó no Marquez, acima da tarefa de carga dela e da Bronze."""
    for fonte, (ns, name) in FONTES.items():
        node = f"dataset:{ns}:{name}"
        r = in_container("curl -sf 'http://marquez-api:5000/api/v1/lineage?depth=2&nodeId="
                         + urllib.parse.quote(node, safe="") + "'")
        if r.returncode != 0 or not r.stdout.strip():
            failures.append(f"Marquez sem o nó da fonte {fonte} ({node})")
            continue
        nodes = {n["id"] for n in json.loads(r.stdout)["graph"]}
        job = f"job:{NS}:{DAG}.ingestao.{fonte}"
        if job not in nodes:
            failures.append(f"a fonte {fonte} não chega na tarefa {DAG}.ingestao.{fonte} no Marquez")
    say("  Fase 4: " + ("um nó por fonte acima da Bronze no Marquez" if not [f for f in failures if "fonte" in f]
                        else "linhagem das fontes INCOMPLETA"))


def main() -> int:
    failures = []
    say("Linhagem ao vivo (3 execuções em modo shadow; nenhuma espera aprovação)")
    sc004 = {}

    def measure(enc, ti):
        # SC-004: do fim da tarefa do agente até o agent.run aparecer no Phoenix
        while ti["state"] == "running":
            time.sleep(1)
            ti = api(f"/dags/{DAG}/dagRuns/{enc}/taskInstances/agente.executar")
        tid = xcom(enc, "agente.executar").get("trace_id")
        if tid:
            sc004["secs"] = wait_for_phoenix_trace(tid, 60)
    a = run_and_wait("A (Marquez no ar)", on_agent=measure)
    a["sc004"] = sc004.get("secs")
    say(f"  SC-004: agent.run no Phoenix {a['sc004']:.1f} s depois do fim da tarefa do agente" if a["sc004"] is not None
        else "  SC-004: agent.run NÃO apareceu no Phoenix em 60 s")
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

    phase3(a, failures)
    phase4_sources(failures)

    in_container("/opt/venvs/agent/bin/python -c 'from agentready import autonomy; "
                 "from agentready_stack.warehouse import connect; "
                 "c=connect(); autonomy.set_override(c, None); c.close()'")
    say("  override de autonomia limpo")
    if failures:
        say("FALHOU:\n  - " + "\n  - ".join(failures))
        return 1
    say(f"OK: linhagem completa; execução sem o Marquez igual à com Marquez; reexecução = novas runs "
        f"({jobs1} jobs, runs do agente {runs1} → {runs2}). Traces: Phoenix = log de auditoria; SC-004 "
        f"{a['sc004']:.1f} s; Phoenix e coletor fora do ar não mudam a execução; reinício preserva os traces.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
