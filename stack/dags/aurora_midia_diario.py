"""DAG aurora_midia_diario — o dia da Aurora Cosméticos rodado por ferramentas de produção.

ingestão → contratos (dbt: quarentena + disjuntor + Silver + testes do contrato) → Gold (dbt)
→ agente (o MESMO da trilha padrão) → aprovação humana (HITL) → fechamento.

Interface: specs/001-stack-production-track/contracts/dag-interface.md
As etapas do agente rodam no venv isolado do agente via `agentready-stack task ...` (os mesmos
comandos que você pode rodar à mão). O Airflow só orquestra.
"""
from __future__ import annotations

import json
import os
import subprocess
from datetime import timedelta
from pathlib import Path

import pendulum
import yaml
from airflow.providers.standard.operators.hitl import HITLOperator
from airflow.sdk import DAG, Param, TaskGroup, task
from cosmos import DbtTaskGroup, ExecutionConfig, ProfileConfig, ProjectConfig, RenderConfig
from cosmos.constants import ExecutionMode, InvocationMode, LoadMode

DBT_PROJECT = Path(os.environ.get("DBT_PROJECT_DIR", "/opt/airflow/dbt/aurora"))
DBT_BIN = os.environ.get("STACK_DBT_BIN", "/opt/venvs/dbt/bin/dbt")
STACK_CLI = os.environ.get("STACK_CLI", "/opt/venvs/agent/bin/agentready-stack")
CONFIG = yaml.safe_load(Path(os.environ.get("STACK_CONFIG", "/opt/airflow/config/stack.yaml")).read_text())
TZ = os.environ.get("TZ", "America/Sao_Paulo")
POOL = "duckdb_writer"


def _duration(text: str) -> timedelta:
    n, unit = int(text[:-1]), text[-1]
    return {"m": timedelta(minutes=n), "h": timedelta(hours=n), "d": timedelta(days=n)}[unit]


def run_stack(*args: str, env: dict | None = None) -> dict:
    """Roda `agentready-stack` no venv do agente, repassa o relato ao log e devolve a última linha (JSON)."""
    proc = subprocess.run([STACK_CLI, *args], capture_output=True, text=True, env=os.environ | (env or {}))
    for line in proc.stdout.splitlines()[:-1]:
        print(line)
    if proc.stderr:
        print(proc.stderr)
    if proc.returncode != 0:
        raise RuntimeError(f"agentready-stack {' '.join(args[:2])} terminou com código {proc.returncode}")
    return json.loads(proc.stdout.splitlines()[-1])


profile = ProfileConfig(profile_name="aurora", target_name="stack", profiles_yml_filepath=DBT_PROJECT / "profiles.yml")
# dbt vive no próprio venv: subprocesso, nunca dbtRunner dentro do processo do Airflow.
execution = ExecutionConfig(execution_mode=ExecutionMode.LOCAL, invocation_mode=InvocationMode.SUBPROCESS,
                            dbt_executable_path=DBT_BIN)


def dbt_group(group_id: str, tag: str, extra_vars: dict | None = None) -> DbtTaskGroup:
    return DbtTaskGroup(
        group_id=group_id,
        project_config=ProjectConfig(DBT_PROJECT),
        profile_config=profile,
        execution_config=execution,
        render_config=RenderConfig(select=[f"tag:{tag}"], load_method=LoadMode.DBT_LS, dbt_deps=False,
                                   invocation_mode=InvocationMode.SUBPROCESS, dbt_executable_path=DBT_BIN),
        operator_args={"pool": POOL, "install_deps": False, **({"vars": extra_vars} if extra_vars else {})},
    )


with DAG(
    dag_id="aurora_midia_diario",
    description="Orçamento de mídia da Aurora: contratos → Gold → agente → aprovação humana",
    schedule=CONFIG["schedule"],
    start_date=pendulum.datetime(2026, 11, 1, tz=TZ),
    catchup=False,
    max_active_runs=1,
    default_args={"retries": 1, "retry_delay": timedelta(seconds=30)},
    tags=["workshop", "bloco-1", "bloco-4", "stack-fase-1"],
    params={
        "reset_scenario": Param(False, type="boolean", description="Gera o cenário do zero (reset completo)"),
        "backfill_meta": Param(False, type="boolean", description="Chegam os lotes atrasados da Meta"),
        "incident": Param("nenhum", enum=["nenhum", "centavos", "renomeacao", "lote_duplicado", "feed_parado",
                                          "aleatorio"], description="Incidente upstream (Bloco 5)"),
        "autonomy_override": Param("manter", enum=["manter", "shadow", "supervised", "guarded", "full", "limpar"],
                                   description="Override global da escada de autonomia"),
        "brain": Param("rules", enum=["rules", "claude"], description="Cérebro do agente (claude exige chave)"),
        "gullible": Param(False, type="boolean", description="Bloco 3: agente que 'acreditou' no briefing"),
    },
    doc_md=__doc__,
) as dag:

    with TaskGroup("ingestao"):
        @task(pool=POOL)
        def preparar(params=None) -> dict:
            return run_stack("task", "ingest", env={"STACK_PARAMS": json.dumps(dict(params or {}))})

        ingestao = preparar()

    contratos = dbt_group("contratos", "contrato")
    gold = dbt_group("gold", "gold", {"reference_ts": "{{ ti.xcom_pull(task_ids='ingestao.preparar')['reference_ts'] }}"})

    with TaskGroup("agente"):
        @task(pool=POOL)
        def executar(params=None, run_id=None) -> dict:
            p = dict(params or {})
            args = ["task", "run-agent", "--brain", p.get("brain", "rules"), "--dag-run-id", str(run_id)]
            return run_stack(*args, *(["--gullible"] if p.get("gullible") else []))

        agente = executar()

    with TaskGroup("aprovacao"):
        @task
        def formularios(resultado: dict) -> list[dict]:
            return resultado.get("hitl", [])

        @task
        def pedidos(resultado: dict) -> list[str]:
            return [r["request_id"] for r in resultado.get("requests", [])]

        approvals_cfg = CONFIG["approvals"]
        revisar = HITLOperator.partial(
            task_id="revisar",
            options=["Aprovar", "Rejeitar"],
            defaults=["Rejeitar"],                       # só no timeout; registrado como EXPIRADO
            response_timeout=_duration(approvals_cfg["response_timeout"]),
            assigned_users=[{"id": u, "name": u} for u in approvals_cfg["approvers"]],
            params={"comentario": Param("", type="string", description="Comentário opcional")},
            retries=0,
        ).expand_kwargs(formularios(agente))

        @task(trigger_rule="all_done", pool=POOL)
        def aplicar(request_id: str, ti=None) -> dict:
            payload = ti.xcom_pull(task_ids="aprovacao.revisar", map_indexes=ti.map_index)
            args = ["task", "apply", "--request-id", request_id]
            if payload:
                args += ["--payload", json.dumps(payload, default=str)]
            return run_stack(*args)

        aplicacoes = aplicar.expand(request_id=pedidos(agente))
        revisar >> aplicacoes

    with TaskGroup("fechamento"):
        @task(trigger_rule="none_failed", pool=POOL)
        def marca_d_agua(run_id=None) -> dict:
            return run_stack("task", "close", "--dag-run-id", str(run_id))

        fechamento = marca_d_agua()

    ingestao >> contratos >> gold >> agente
    [agente, aplicacoes] >> fechamento
