"""Fase 4 — o grupo de ingestão: parâmetros + uma tarefa por fonte (roda com o Python do Airflow; NÃO importa
agentready_stack). contracts/dag-interface.md; o passo de parâmetros manteve o id `ingestao.preparar` (Fase 1)."""
import os
from pathlib import Path

import pytest

DAGS = Path(os.environ.get("STACK_DAGS_DIR", Path(__file__).resolve().parents[1] / "dags"))
FONTES = {"ads": ("fonte://ads", "investimento", "bronze_raw.ad_spend", "bronze.ad_spend"),
          "ga4": ("fonte://ga4", "conversoes", "bronze_raw.conversions__ga4", "bronze.conversions"),
          "meta_capi": ("fonte://meta", "conversoes", "bronze_raw.conversions__meta_capi", "bronze.conversions"),
          "catalogo": ("fonte://catalogo", "campanhas", "bronze_raw.campaigns", "bronze.campaigns")}


@pytest.fixture(scope="module")
def dag():
    from airflow.dag_processing.dagbag import DagBag
    bag = DagBag(dag_folder=str(DAGS))
    assert not bag.import_errors, bag.import_errors
    return bag.get_dag("aurora_midia_diario")


def _ds(items):
    return {(d.namespace, d.name) for d in items}


def test_ingestion_group_is_params_plus_one_task_per_source(dag):
    group = {t.task_id for t in dag.tasks if t.task_id.startswith("ingestao.")}
    assert group == {"ingestao.preparar", *(f"ingestao.{f}" for f in FONTES)}
    lint = dag.get_task("contratos.lint")
    for f, (ns, name, raw, bronze) in FONTES.items():
        t = dag.get_task(f"ingestao.{f}")
        assert t.upstream_task_ids == {"ingestao.preparar"}
        assert t.task_id in lint.upstream_task_ids, "o estágio de contrato espera todas as cargas"
        assert t.retries == 0, "o dlt já tenta de novo; retentativa da tarefa esconderia um `falhou`"
        assert t.pool == "duckdb_writer"
        assert _ds(t.inlets) == {(ns, name)}
        assert _ds(t.outlets) == {("duckdb:///opt/stack-data/ops.duckdb", f"warehouse.{raw}"),
                                  ("duckdb:///opt/stack-data/ops.duckdb", f"warehouse.{bronze}")}


def test_phase4_params(dag):
    p = dag.params
    assert p["falhas_upstream"] == "padrao" and p["fonte_fora_do_ar"] == "nenhuma"
    spec = {k: dag.params.get_param(k).schema for k in ("falhas_upstream", "fonte_fora_do_ar")}
    assert spec["falhas_upstream"]["enum"] == ["padrao", "nenhuma", "todas"]
    assert spec["fonte_fora_do_ar"]["enum"] == ["nenhuma", "ads", "ga4", "meta_capi", "catalogo"]


def test_tags(dag):
    assert {"stack-fase-4", "bloco-3"} <= set(dag.tags)
