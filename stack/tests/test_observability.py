"""Vereditos de observabilidade da trilha stack (Fase 2, US1: FR-001–FR-007, pesquisa R2/R6/R7).

As regras são as da trilha padrão (observability.py), reescritas como modelos dbt `obs_*`.
Os valores esperados aqui vêm da trilha padrão no mesmo cenário; a igualdade EXATA entre as duas
trilhas é provada em test_parity.py.
"""
import json
from pathlib import Path

import pytest

from agentready.db import connect, rows

SCHEMA = Path("/opt/agentready/specs/002-stack-lineage-observability/contracts/observability-check.schema.json")
if not SCHEMA.exists():
    SCHEMA = Path(__file__).resolve().parents[2] / "specs" / "002-stack-lineage-observability" / "contracts" / \
        "observability-check.schema.json"

# Na manhã do cenário o feed da Meta está parado de propósito: frescor e volume da meta_capi falham
# nas duas trilhas (medido na trilha padrão em 2026-11-25).
MORNING_FAILS = {("frescor", "conversions/meta_capi"), ("volume", "conversions/meta_capi")}


def verdicts():
    c = connect()
    try:
        return rows(c, "SELECT * FROM meta.observability_checks ORDER BY pillar, target")
    finally:
        c.close()


def fails(vs):
    return {(v["pillar"], v["target"]) for v in vs if v["status"] == "fail"}


def test_clean_morning_fails_only_the_stale_meta_feed(built):
    vs = verdicts()
    assert {v["pillar"] for v in vs} == {"frescor", "volume", "distribuição", "esquema"}
    assert fails(vs) == MORNING_FAILS


def test_centavos_passes_contract_fails_distribution(run_incident):
    run_incident("centavos", breaker=False)
    c = connect()
    st = rows(c, "SELECT status FROM meta.batch_status WHERE batch_id LIKE '%-redelivery'")
    c.close()
    assert st == [{"status": "passed"}], "o contrato aprova o lote em centavos: essa é a lacuna"
    dist = [v for v in verdicts() if v["pillar"] == "distribuição" and v["target"] == "conversions/ga4.order_value_brl"]
    assert len(dist) == 1 and dist[0]["status"] == "fail"
    assert "-redelivery" in dist[0]["detail"] and dist[0]["ratio"] > 50
    assert dist[0]["detail"].startswith("ticket médio do último lote ")


@pytest.mark.parametrize("kind,pillar,target", [
    ("centavos", "distribuição", "conversions/ga4.order_value_brl"),
    ("renomeacao", "esquema", "bronze.conversions"),
    ("lote_duplicado", "volume", "conversions/ga4"),
    ("feed_parado", "frescor", "conversions/ga4"),
])
def test_incident_pillar(run_incident, kind, pillar, target):
    run_incident(kind)
    assert (pillar, target) in fails(verdicts()), fails(verdicts())


def test_renomeacao_schema_detail_matches_default_wording(run_incident):
    run_incident("renomeacao")
    esq = [v for v in verdicts() if v["pillar"] == "esquema" and v["target"] == "bronze.conversions"][0]
    assert esq["detail"] == "colunas inesperadas ['utm_campaign']; campaign_id 100% nulo no último lote"


def test_short_history_warns(short_history, dbt):
    dbt()
    vs = verdicts()
    warned = [v for v in vs if v["pillar"] in ("volume", "distribuição") and v["status"] == "warn"]
    assert warned, vs
    assert all("histórico insuficiente" in v["detail"] for v in warned)
    assert not [v for v in vs if v["pillar"] in ("volume", "distribuição") and v["status"] == "pass"
                and v["target"].startswith("conversions/ga4")], "com 3 dias, a ga4 não tem linha de base"


def test_verdicts_match_schema(built):
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads(SCHEMA.read_text())
    for v in verdicts():
        jsonschema.validate({**v, "reference_ts": v["reference_ts"].isoformat()}, schema)


def test_observe_task_fails_on_fail_verdicts_and_prints_ptbr_table(built, capsys):
    from agentready_stack import observe, tasks
    with pytest.raises(observe.ObservabilityAlert):
        tasks.observe()
    out = capsys.readouterr().out
    assert "pilar" in out and "detalhe" in out and "❌" in out and "conversions/meta_capi" in out


def test_report_failure_is_warning(built, monkeypatch, capsys):
    from agentready_stack import tasks
    monkeypatch.setenv("STACK_EDR_BIN", "/nao/existe/edr")
    out = tasks.build_report()
    assert out["ok"] is False
    assert "relatório de observabilidade não atualizado" in capsys.readouterr().out
