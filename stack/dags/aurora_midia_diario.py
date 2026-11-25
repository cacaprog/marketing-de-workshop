"""DAG aurora_midia_diario — o dia da Aurora Cosméticos rodado por ferramentas de produção.

ingestão → contratos (dbt: quarentena + disjuntores + Silver + testes do contrato) → Gold (dbt)
→ observabilidade (Fase 2: 4 pilares em dbt + Elementary) → agente (o MESMO da trilha padrão)
→ aprovação humana (HITL) → fechamento.

Interface: specs/001-stack-production-track/contracts/dag-interface.md (Fase 1) e
specs/002-stack-lineage-observability/contracts/dag-interface.md (Fase 2).
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
from cosmos.constants import ExecutionMode, InvocationMode, LoadMode, TestBehavior
from cosmos.operators.local import DbtTestLocalOperator
from openlineage.client.event_v2 import Dataset

DBT_PROJECT = Path(os.environ.get("DBT_PROJECT_DIR", "/opt/airflow/dbt/aurora"))
DBT_BIN = os.environ.get("STACK_DBT_BIN", "/opt/venvs/dbt/bin/dbt")
STACK_CLI = os.environ.get("STACK_CLI", "/opt/venvs/agent/bin/agentready-stack")
SYNC_SCRIPT = os.environ.get("STACK_CONTRACTS_SYNC", "/opt/agentready/stack/scripts/contracts-sync.sh")
CONFIG = yaml.safe_load(Path(os.environ.get("STACK_CONFIG", "/opt/airflow/config/stack.yaml")).read_text())
TZ = os.environ.get("TZ", "America/Sao_Paulo")
POOL = "duckdb_writer"
# Valores que a ingestão decide para esta execução (XCom de ingestao.preparar), repassados ao dbt.
_PREP = "ti.xcom_pull(task_ids='ingestao.preparar')"
REF_VAR = "{{ " + _PREP + "['reference_ts'] }}"
BREAKER_VAR = "{{ " + _PREP + "['breaker']['value'] }}"
# Linhagem das tarefas Python (FR-009/FR-010): os MESMOS nomes que o Cosmos/dbt emite para o DuckDB
# (namespace = arquivo do warehouse; nome = <catálogo>.<schema>.<tabela>), para o grafo se ligar no Marquez.
WAREHOUSE_NS = "duckdb:///opt/stack-data/warehouse.duckdb"


def ds(*tables: str) -> list[Dataset]:
    return [Dataset(namespace=WAREHOUSE_NS, name=f"warehouse.{t}") for t in tables]


OBS_VARS = {"min_history": "{{ " + _PREP + "['min_history'] }}",
            "obs_bands": "{{ " + _PREP + "['obs_bands'] | tojson }}"}


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


def dbt_group(group_id: str, tag: str, extra_vars: dict | None = None,
              test_behavior: TestBehavior = TestBehavior.AFTER_EACH) -> DbtTaskGroup:
    return DbtTaskGroup(
        group_id=group_id,
        project_config=ProjectConfig(DBT_PROJECT),
        profile_config=profile,
        execution_config=execution,
        render_config=RenderConfig(select=[f"tag:{tag}"], load_method=LoadMode.DBT_LS, dbt_deps=False,
                                   invocation_mode=InvocationMode.SUBPROCESS, dbt_executable_path=DBT_BIN,
                                   test_behavior=test_behavior),
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
    tags=["workshop", "bloco-1", "bloco-4", "bloco-5", "stack-fase-2"],
    params={
        "reset_scenario": Param(False, type="boolean", description="Gera o cenário do zero (reset completo)"),
        "backfill_meta": Param(False, type="boolean", description="Chegam os lotes atrasados da Meta"),
        "incident": Param("nenhum", enum=["nenhum", "centavos", "renomeacao", "lote_duplicado", "feed_parado",
                                          "aleatorio"], description="Incidente upstream (Bloco 5)"),
        "autonomy_override": Param("manter", enum=["manter", "shadow", "supervised", "guarded", "full", "limpar"],
                                   description="Override global da escada de autonomia"),
        "brain": Param("rules", enum=["rules", "claude"], description="Cérebro do agente (claude exige chave)"),
        "gullible": Param(False, type="boolean", description="Bloco 3: agente que 'acreditou' no briefing"),
        "disjuntor_distribuicao": Param("compartilhado", enum=["compartilhado", "ligado", "desligado"],
                                        description="Disjuntor de distribuição só nesta execução (Bloco 5); "
                                                    "'compartilhado' usa config/guardrails.yaml"),
    },
    doc_md=__doc__,
) as dag:

    with TaskGroup("ingestao"):
        @task(pool=POOL, outlets=ds("bronze.campaigns", "bronze.ad_spend", "bronze.conversions"))
        def preparar(params=None, run_id=None) -> dict:
            """Ingestão: aplica os parâmetros da execução (cenário, backfill da Meta, incidente do Bloco 5,
            autonomia) e decide o disjuntor de distribuição DESTA execução. Escreve na Bronze."""
            return run_stack("task", "ingest", "--dag-run-id", str(run_id),
                             env={"STACK_PARAMS": json.dumps(dict(params or {}))})

        ingestao = preparar()

    with TaskGroup("contratos"):
        @task(pool=POOL)
        def lint() -> None:
            """datacontract lint em cada contrato ODCS + regenera os testes dbt da Silver (nunca versionados)."""
            proc = subprocess.run([SYNC_SCRIPT], capture_output=True, text=True)
            print(proc.stdout, proc.stderr)
            if proc.returncode != 0:
                raise RuntimeError("contrato inválido: a execução para aqui (um contrato ilegível não é adivinhado)")

        contratos_lint = lint()
        # Fase 2: o disjuntor de distribuição mora no estágio de contrato (pesquisa R3).
        contratos = dbt_group("verificar", "contrato", OBS_VARS | {"block_on_distribution_anomaly": BREAKER_VAR})

        # retries=0: uma retentativa rodaria DEPOIS do fechamento mover a marca d'água e apagaria o alerta.
        @task(pool=POOL, retries=0)
        def alerta_qualidade() -> dict:
            return run_stack("task", "alert")

        alerta = alerta_qualidade()
        contratos_lint >> contratos >> alerta
    gold = dbt_group("gold", "gold", {"reference_ts": REF_VAR})

    with TaskGroup("observabilidade"):
        # Fase 2: os 4 pilares (modelos obs_*) rodam DEPOIS da Gold (o frescor lê gold.source_health) e
        # ANTES do agente. Só os modelos ficam no caminho do agente: um modelo que não roda segura o
        # agente (FR-008b), mas um VEREDITO com falha não (US1 AS2) — os testes rodam numa tarefa folha.
        obs_verificar = dbt_group("verificar", "observabilidade", OBS_VARS | {"reference_ts": REF_VAR},
                                  test_behavior=TestBehavior.NONE)

        obs_testes = DbtTestLocalOperator(
            task_id="testes",
            project_dir=str(DBT_PROJECT),
            profile_config=profile,
            dbt_executable_path=DBT_BIN,
            invocation_mode=InvocationMode.SUBPROCESS,
            select=["tag:veredito_observabilidade"],
            vars=OBS_VARS | {"reference_ts": REF_VAR},
            install_deps=False,
            pool=POOL,
            retries=0,
            doc_md="Testes de veredito (severity error): vermelho aqui = algum pilar falhou. "
                   "O Elementary grava cada resultado (histórico no relatório).",
        )

        @task(pool=POOL, retries=0, inlets=ds("meta.observability_checks"))
        def resumo() -> dict:
            """Tabela dos 4 pilares em pt-BR (o mesmo formato do `agentready observe`)."""
            return run_stack("task", "observe")

        @task(pool=POOL, retries=0, trigger_rule="all_done")
        def relatorio() -> dict:
            """Relatório web do Elementary (http://localhost:8090). Falhar aqui é só um aviso."""
            return run_stack("task", "report")

        obs_resumo = resumo()
        obs_relatorio = relatorio()
        obs_verificar >> [obs_testes, obs_resumo]
        obs_testes >> obs_relatorio

    with TaskGroup("agente"):
        @task(pool=POOL, inlets=ds("gold.campaign_daily", "gold.source_health", "meta.batch_status"),
              outlets=ds("ops.change_log", "ops.approval_queue", "ops.campaigns"))
        def executar(params=None, run_id=None) -> dict:
            """O agente de orçamento — o MESMO da trilha padrão. Lê gold.campaign_daily, gold.source_health e
            meta.batch_status; executa ou enfileira ajustes (ops.change_log, ops.approval_queue, ops.campaigns).
            Na linhagem, o facet agentready_trace traz o trace_id (o mesmo de ops.change_log) e o status:
            'done' = decidiu; 'skipped_duplicate' = mesmos dados de antes, o agente não rodou."""
            p = dict(params or {})
            args = ["task", "run-agent", "--brain", p.get("brain", "rules"), "--dag-run-id", str(run_id)]
            return run_stack(*args, *(["--gullible"] if p.get("gullible") else []))

        agente = executar()

    with TaskGroup("aprovacao"):
        @task
        def formularios(resultado: dict) -> list[dict]:
            """Monta um formulário de aprovação por pedido que o agente enfileirou."""
            return resultado.get("hitl", [])

        @task
        def pedidos(resultado: dict) -> list[str]:
            """Lista os pedidos de aprovação desta execução."""
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

        @task(trigger_rule="all_done", pool=POOL, inlets=ds("ops.approval_queue", "ops.campaigns"),
              outlets=ds("ops.change_log", "ops.campaigns"))
        def aplicar(request_id: str, ti=None) -> dict:
            """Aplica a decisão humana pelo caminho da trilha padrão: reverifica o estado vivo antes de
            executar; rejeição e expiração não mudam nada. Grava em ops.change_log."""
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
            """Fechamento: marca d'água (base do alerta "só problemas novos"), resumo da execução e
            verificação da linhagem (Marquez fora do ar = aviso, nunca falha)."""
            return run_stack("task", "close", "--dag-run-id", str(run_id))

        fechamento = marca_d_agua()

    ingestao >> contratos_lint
    contratos >> gold >> obs_verificar >> agente   # alerta, testes, resumo e relatório são folhas
    [agente, aplicacoes] >> fechamento
