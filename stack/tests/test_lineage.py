"""Linhagem emitida pelo próprio pipeline (Fase 2, US3: FR-009–FR-011, contracts/lineage-events.md).

Testes AO VIVO: precisam da stack no ar e de pelo menos uma execução do DAG (`make test-live` cuida
disso). Sem Marquez acessível, são pulados com uma mensagem clara.
"""
import json
import os
import urllib.parse
import urllib.request

import duckdb
import pytest

NS = "aurora"
DAG = "aurora_midia_diario"
WAREHOUSE_NS = "duckdb:///opt/stack-data/warehouse.duckdb"
LIVE_DB = os.environ.get("STACK_LIVE_DB", "/opt/stack-data/warehouse.duckdb")
API = os.environ.get("STACK_AIRFLOW_API", "http://airflow-apiserver:8080")
TERMINAL = {"success", "failed", "upstream_failed"}


def _get(url, headers=None):
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.load(r)


def _job(marquez, name):
    return _get(f"{marquez}/api/v1/namespaces/{NS}/jobs/{urllib.parse.quote(name, safe='')}")


@pytest.fixture(scope="module")
def airflow():
    pw = json.load(open(os.environ.get("STACK_PASSWORDS", "/opt/airflow/config/passwords.json")))["instrutor"]
    req = urllib.request.Request(f"{API}/auth/token", data=json.dumps({"username": "instrutor", "password": pw}).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        tok = json.load(urllib.request.urlopen(req, timeout=10))["access_token"]
    except OSError:
        pytest.skip("API do Airflow indisponível: rode `make test-live` com a stack no ar")
    h = {"Authorization": f"Bearer {tok}"}
    runs = _get(f"{API}/api/v2/dags/{DAG}/dagRuns?order_by=-start_date&limit=1", h)["dag_runs"]
    if not runs:
        pytest.skip("nenhuma execução do DAG ainda: rode `make run`")
    run_id = runs[0]["dag_run_id"]
    tis = _get(f"{API}/api/v2/dags/{DAG}/dagRuns/{urllib.parse.quote(run_id, safe='')}/taskInstances?limit=500", h)
    return {"run_id": run_id, "task_instances": tis["task_instances"]}


def test_graph_has_agent_with_inputs_outputs_and_trace(marquez):
    job = _job(marquez, f"{DAG}.agente.executar")
    ins = {(d["namespace"], d["name"]) for d in job["inputs"]}
    outs = {(d["namespace"], d["name"]) for d in job["outputs"]}
    for t in ("gold.campaign_daily", "gold.source_health", "meta.batch_status"):
        assert (WAREHOUSE_NS, f"warehouse.{t}") in ins, ins
    for t in ("ops.change_log", "ops.approval_queue", "ops.campaigns"):
        assert (WAREHOUSE_NS, f"warehouse.{t}") in outs, outs
    facet = (job["latestRun"]["facets"] or {}).get("agentready_trace")
    con = duckdb.connect(LIVE_DB, read_only=True)
    try:
        traces = {r[0] for r in con.execute("SELECT trace_id FROM ops.agent_runs WHERE trace_id IS NOT NULL").fetchall()}
    finally:
        con.close()
    if facet is None:
        # execução pulada pelo livro-razão (skipped_duplicate) não tem trace: procure numa execução anterior
        runs = _get(f"{marquez}/api/v1/namespaces/{NS}/jobs/{urllib.parse.quote(f'{DAG}.agente.executar', safe='')}/runs?limit=20")
        facet = next((r["facets"]["agentready_trace"] for r in runs["runs"] if "agentready_trace" in (r["facets"] or {})), None)
    assert facet is not None, "nenhuma execução do agente com o facet agentready_trace"
    assert facet["trace_id"] in traces, "o trace_id da linhagem tem de existir no livro-razão do agente"


def test_path_from_bronze_to_agent(marquez):
    g = _get(f"{marquez}/api/v1/lineage?nodeId=" + urllib.parse.quote(f"dataset:{WAREHOUSE_NS}:warehouse.bronze.conversions")
             + "&depth=20")
    nodes = {n["id"] for n in g["graph"]}
    assert f"job:{NS}:{DAG}.agente.executar" in nodes, "o caminho bronze.conversions → … → agente não existe no Marquez"
    for t in ("silver.conversions", "gold.campaign_daily"):
        assert f"dataset:{WAREHOUSE_NS}:warehouse.{t}" in nodes


def test_every_task_has_an_event(marquez, airflow):
    dag_job = _job(marquez, DAG)
    parent_ids = {r["id"] for r in dag_job.get("latestRuns", [])} | {dag_job["latestRun"]["id"]}
    missing = []
    for ti in airflow["task_instances"]:
        if ti["state"] not in TERMINAL:
            continue
        try:
            job = _job(marquez, f"{DAG}.{ti['task_id']}")
        except OSError:
            missing.append(ti["task_id"])
            continue
        runs = [job["latestRun"]] + job.get("latestRuns", [])
        if not any(((r.get("facets") or {}).get("parent") or {}).get("run", {}).get("runId") in parent_ids for r in runs):
            missing.append(ti["task_id"])
    assert not missing, f"tarefas sem evento OpenLineage sob a execução do DAG: {sorted(set(missing))}"
