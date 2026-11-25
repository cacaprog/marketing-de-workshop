"""Paridade da Fase 2 (US2: FR-015, SC-003): além de Gold, saúde das fontes e decisões, as duas trilhas
dão o MESMO veredito por pilar e alvo — nos 3 cenários da Fase 1 e em um cenário por incidente.
O único mapeamento permitido: 'warn' (histórico insuficiente) da stack vale como 'pass' (pesquisa R7)."""
import json
from pathlib import Path

import jsonschema
import pytest

from agentready_stack import parity

from conftest import REF

SCHEMA_CANDIDATES = [Path("/opt/agentready/specs/002-stack-lineage-observability/contracts/parity-report.schema.json"),
                     Path(__file__).resolve().parents[2] / "specs/002-stack-lineage-observability/contracts/parity-report.schema.json"]
SCHEMA = json.loads(next(p for p in SCHEMA_CANDIDATES if p.exists()).read_text())


def _sides(scenario):
    return parity.run_side("default", scenario, REF), parity.run_side("stack", scenario, REF)


@pytest.mark.parametrize("scenario", parity.ALL_SCENARIOS)
def test_tracks_identical_including_observability(scenario):
    default, stack = _sides(scenario)          # incident_build_does_not_crash: run_side levanta se o build cair
    report = parity.compare_full(default, stack, scenario, REF)
    jsonschema.validate(report, SCHEMA)
    diffs = {k: v["diffs"] for k, v in report["compared"].items() if v["diffs"]}
    assert report["ok"], json.dumps(diffs, ensure_ascii=False, default=str)[:3000]
    assert report["compared"]["observability"]["items"] >= 10


@pytest.mark.parametrize("scenario,pillar,target", [
    ("incidente_centavos", "distribuição", "conversions/ga4.order_value_brl"),
    ("incidente_renomeacao", "esquema", "bronze.conversions"),
    ("incidente_lote_duplicado", "volume", "conversions/ga4"),
    ("incidente_feed_parado", "frescor", "conversions/ga4"),
])
def test_incident_pillar_fails_on_both_tracks(scenario, pillar, target):
    for side in _sides(scenario):
        assert [pillar, target, "fail"] in side["observability"]


def test_band_drift_is_reported(monkeypatch):
    """US2 AS3: mudar a faixa de um lado tem de aparecer como diferença, nunca passar em silêncio."""
    monkeypatch.setenv("STACK_PARITY_EXTRA_VARS", json.dumps({"obs_bands": {"volume": [0.5, 1.5],
                                                                            "distribution": [1.5, 2.0]}}))
    default = parity.run_side("default", "manha", REF)
    stack = parity.run_side("stack", "manha", REF)
    report = parity.compare_full(default, stack, "manha", REF)
    assert not report["ok"]
    assert any(d["key"].startswith("distribuição|") for d in report["compared"]["observability"]["diffs"])


def test_warn_maps_to_pass_and_only_that(short_history, dbt):
    from agentready.db import connect
    dbt()
    c = connect()
    try:
        raw = c.execute("SELECT pillar, target, status FROM meta.observability_checks WHERE status='warn'").fetchall()
        mapped = parity._verdicts("stack", c)
    finally:
        c.close()
    assert raw, "o cenário curto deveria ter avisos"
    p, t, _ = raw[0]
    assert [p, t, "pass"] in mapped and [p, t, "warn"] not in mapped
    base = {"campaign_daily": [], "source_health": [], "decisions": []}
    same = parity.compare_full(base | {"observability": [[p, t, "pass"]]}, base | {"observability": [[p, t, "pass"]]},
                               "manha", REF)
    differ = parity.compare_full(base | {"observability": [[p, t, "fail"]]}, base | {"observability": [[p, t, "pass"]]},
                                 "manha", REF)
    assert same["ok"] and not differ["ok"]
