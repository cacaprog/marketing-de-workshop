"""Integridade do DAG (roda com o Python do Airflow; NÃO importa agentready_stack)."""
import os
from pathlib import Path

import pytest

DAGS = Path(os.environ.get("STACK_DAGS_DIR", Path(__file__).resolve().parents[1] / "dags"))


@pytest.fixture(scope="module")
def dag():
    from airflow.dag_processing.dagbag import DagBag
    bag = DagBag(dag_folder=str(DAGS))
    assert not bag.import_errors, bag.import_errors
    return bag.get_dag("aurora_midia_diario")


def _group(task_id: str) -> str:
    return task_id.split(".")[0]


def test_run_policy(dag):
    assert dag.max_active_runs == 1
    assert dag.catchup is False
    assert dag.schedule is not None


def test_stage_order(dag):
    order = ["ingestao", "contratos", "gold", "agente", "aprovacao", "fechamento"]
    groups = {_group(t.task_id) for t in dag.tasks}
    assert set(order) <= groups, groups
    # cada grupo depende (transitivamente) do anterior
    for before, after in zip(order, order[1:]):
        if (before, after) == ("aprovacao", "fechamento"):
            continue  # fechamento depende de agente + aplicar (pode não haver aprovações)
        first_after = [t for t in dag.tasks if _group(t.task_id) == after]
        ups = set()
        for t in first_after:
            ups |= {u.task_id for u in t.get_flat_relatives(upstream=True)}
        assert any(_group(u) == before for u in ups), f"{after} não depende de {before}"


def test_closing_runs_without_approvals(dag):
    close = dag.get_task("fechamento.marca_d_agua")
    assert str(close.trigger_rule) in ("none_failed", "TriggerRule.NONE_FAILED")
    assert {"agente.executar", "aprovacao.aplicar"} <= set(close.upstream_task_ids)


def test_writers_use_the_single_writer_pool(dag):
    writers = [t for t in dag.tasks if _group(t.task_id) in ("ingestao", "contratos", "gold", "agente", "fechamento")
               or t.task_id == "aprovacao.aplicar"]
    assert writers
    assert all(t.pool == "duckdb_writer" for t in writers), [(t.task_id, t.pool) for t in writers if t.pool != "duckdb_writer"]


def test_params_match_interface(dag):
    p = dag.params
    assert p["reset_scenario"] is False and p["backfill_meta"] is False and p["gullible"] is False
    assert p["incident"] == "nenhum" and p["autonomy_override"] == "manter" and p["brain"] == "rules"


def test_approval_task_fails_safe(dag):
    revisar = dag.get_task("aprovacao.revisar")
    kw = revisar.partial_kwargs
    assert kw.get("defaults") == ["Rejeitar"]
    assert kw.get("retries") == 0
    assert kw.get("response_timeout") is not None


def test_lint_gates_the_contract_checks(dag):
    lint = dag.get_task("contratos.lint")
    verificar = [t for t in dag.tasks if t.task_id.startswith("contratos.verificar.")]
    assert verificar
    for t in verificar:
        assert lint.task_id in {u.task_id for u in t.get_flat_relatives(upstream=True)}
    assert "ingestao.preparar" in lint.upstream_task_ids


def test_quality_alert_is_a_leaf(dag):
    alert = dag.get_task("contratos.alerta_qualidade")
    assert not alert.downstream_task_ids, "nada pode depender do alerta: Gold e agente seguem com o último dado bom"
    gold_ups = set()
    for t in dag.tasks:
        if t.task_id.startswith("gold."):
            gold_ups |= {u.task_id for u in t.get_flat_relatives(upstream=True)}
    assert alert.task_id not in gold_ups
    assert alert.retries == 0, "uma retentativa veria a marca d'água nova e esconderia o alerta"
