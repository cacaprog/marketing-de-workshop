"""Paridade (US2, FR-020, SC-002): as duas trilhas produzem a mesma Gold, a mesma saúde das
fontes e as MESMAS decisões do agente — a prova de que só a arquitetura mudou."""
import copy
import json
from pathlib import Path

import jsonschema
import pytest

from agentready_stack import parity

from conftest import REF

SCHEMA_CANDIDATES = [Path("/opt/agentready/specs/001-stack-production-track/contracts/parity-report.schema.json"),
                     Path(__file__).resolve().parents[2] / "specs/001-stack-production-track/contracts/parity-report.schema.json"]
SCHEMA = json.loads(next(p for p in SCHEMA_CANDIDATES if p.exists()).read_text())


@pytest.fixture(scope="module")
def sides():
    """Roda os dois lados de cada cenário uma vez (cada lado: gerar + construir + agente)."""
    return {s: (parity.run_side("default", s, REF), parity.run_side("stack", s, REF)) for s in parity.SCENARIOS}


@pytest.mark.parametrize("scenario", parity.SCENARIOS)
def test_tracks_are_identical(sides, scenario):
    default, stack = sides[scenario]
    report = parity.compare(default, stack, scenario, REF)
    jsonschema.validate(report, SCHEMA)
    assert report["ok"], json.dumps(report["compared"], ensure_ascii=False, indent=1, default=str)[:3000]
    assert report["compared"]["decisions"]["items"] > 0, "o agente tem de ter decidido algo"


def test_scenarios_really_differ(sides):
    """Sanidade: os cenários não são o mesmo teste repetido."""
    manha, pos = sides["manha"][0], sides["pos_backfill"][0]
    stale = lambda side: {(r[0], r[1]) for r in side["source_health"] if r[2] == "stale"}  # noqa: E731
    assert ("conversions", "meta_capi") in stale(manha)
    assert ("conversions", "meta_capi") not in stale(pos)
    sup = {d["status"] for d in sides["supervisionado"][0]["decisions"]}
    assert "queued_for_approval" in sup and "executed" not in sup


def test_a_planted_difference_is_reported(sides):
    default, stack = sides["manha"]
    tampered = copy.deepcopy(stack)
    tampered["campaign_daily"][0][4] = round(tampered["campaign_daily"][0][4] + 1, 2)   # spend_brl + R$ 1
    tampered["decisions"][-1]["status"] = "rejected"
    report = parity.compare(default, tampered, "manha", REF)
    jsonschema.validate(report, SCHEMA)
    assert not report["ok"]
    key = f"{default['campaign_daily'][0][0]}|{default['campaign_daily'][0][1]}"
    assert any(d["key"] == key and d["field"] == "spend_brl" for d in report["compared"]["campaign_daily"]["diffs"])
    assert any(d["field"] == "status" for d in report["compared"]["decisions"]["diffs"])


def test_parity_cli_exit_code_is_zero_when_identical(monkeypatch, sides, capsys):
    from agentready_stack import cli
    monkeypatch.setattr(parity, "run_side", lambda track, scenario, ref: sides[scenario][0 if track == "default" else 1])
    assert cli.main(["parity", "--scenario", "manha", "--reference-ts", REF.isoformat()]) == 0
    assert "0 diferenças" in capsys.readouterr().out
