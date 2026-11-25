"""Fase 3 (FR-010, SC-002): paridade do trace do agente entre as trilhas (contracts/trace-parity.md)."""
from __future__ import annotations

import copy
import json
from datetime import datetime
from pathlib import Path

import jsonschema

from agentready_stack import parity

SCHEMA_CANDIDATES = [Path("/opt/agentready/specs/003-stack-traces-dashboards/contracts/parity-report.schema.json"),
                     Path(__file__).resolve().parents[2] / "specs/003-stack-traces-dashboards/contracts/parity-report.schema.json"]
SCHEMA = json.loads(next(p for p in SCHEMA_CANDIDATES if p.exists()).read_text())
REF = datetime(2026, 11, 25, 9, 0)


def rec(name, span, parent, start, **attrs):
    return {"trace_id": "t" * 32, "span_id": span, "parent_span_id": parent, "name": name, "start_time": start,
            "end_time": start, "status": "OK", "status_message": None, "attributes": attrs, "events": [],
            "prev_hash": "x", "hash": "y"}


RECORDS = [
    rec("agent.run", "a", "worker", "09:00:01", **{"gen_ai.agent.name": "budget-agent"}),
    rec("tool.get_data_health", "b", "a", "09:00:02"),
    rec("tool.adjust_campaign_budget", "c", "a", "09:00:04", campaign_id="C01",
        **{"decision.message": "executado CHG-1a2b3c4d"}),
    rec("tool.adjust_campaign_budget", "d", "a", "09:00:03", campaign_id="C02"),
    rec("x.fora_da_subarvore", "z", "worker", "09:00:00"),
]


def side(trace):
    return {"campaign_daily": [], "source_health": [], "decisions": [], "observability": [], "trace": trace}


def test_normalize_drops_ids_and_times_and_keys_by_path():
    n = parity.normalize_trace(RECORDS)
    keys = [r[0] for r in n]
    assert keys == sorted(keys)
    assert "agent.run#1" in keys
    assert "agent.run/tool.adjust_campaign_budget#C01" in keys and "agent.run/tool.adjust_campaign_budget#C02" in keys
    assert "agent.run/tool.get_data_health#1" in keys
    assert not any("fora_da_subarvore" in k for k in keys), "só a subárvore de agent.run"
    flat = json.dumps(n)
    for leaked in ("09:00", '"a"', "prev_hash", "hash"):
        assert leaked not in flat
    c01 = next(r for r in n if r[0].endswith("#C01"))
    assert c01[3]["decision.message"] == "executado CHG-*", "IDs aleatórios mascarados"


def test_order_of_siblings_does_not_matter():
    shuffled = list(reversed(RECORDS))
    assert parity.normalize_trace(shuffled) == parity.normalize_trace(RECORDS)


def test_attribute_difference_is_reported_per_attribute():
    other = copy.deepcopy(RECORDS)
    other[2]["attributes"]["campaign_id"] = "C01"
    other[2]["attributes"]["params.new_daily_budget_brl"] = 999.0
    rep = parity.compare_all(side(parity.normalize_trace(RECORDS)), side(parity.normalize_trace(other)), "manha", REF)
    diffs = rep["compared"]["traces"]["diffs"]
    assert [d["field"] for d in diffs] == ["attributes.params.new_daily_budget_brl"]
    assert rep["ok"] is False


def test_report_2_1_0_validates_and_older_shapes_stay():
    t = parity.normalize_trace(RECORDS)
    rep = parity.compare_all(side(t), side(copy.deepcopy(t)), "manha", REF)
    jsonschema.validate(rep, SCHEMA)
    assert rep["compared"]["traces"]["diffs"] == [] and rep["ok"] is True
    assert "traces" not in parity.compare_full(side(t), side(t), "manha", REF)["compared"], "2.0.0 inalterado"
    assert "observability" not in parity.compare(side(t), side(t), "manha", REF)["compared"], "1.0.0 inalterado"


def test_live_parity_manha_has_identical_agent_traces():
    from conftest import REF as LIVE_REF
    rep = parity.run("manha", LIVE_REF)
    assert rep["compared"]["traces"]["items"] > 0
    assert rep["compared"]["traces"]["diffs"] == [], rep["compared"]["traces"]["diffs"][:5]


# ------------------------------------------------------------------ achados da revisão (/ship)

def test_same_tool_same_campaign_twice_keeps_both_spans():
    """Agente crédulo: ajuste injetado + corte na MESMA campanha — as duas chaves existem (nada some)."""
    recs = [rec("agent.run", "a", None, "09:00:01"),
            rec("tool.adjust_campaign_budget", "b", "a", "09:00:02", campaign_id="C03", **{"x": 1}),
            rec("tool.adjust_campaign_budget", "c", "a", "09:00:03", campaign_id="C03", **{"x": 2})]
    keys = [r[0] for r in parity.normalize_trace(recs)]
    assert "agent.run/tool.adjust_campaign_budget#C03" in keys
    assert "agent.run/tool.adjust_campaign_budget#C03#2" in keys
    other = copy.deepcopy(recs)
    other[1]["attributes"]["x"] = 99                     # diferença só na PRIMEIRA chamada
    rep = parity.compare_all(side(parity.normalize_trace(recs)), side(parity.normalize_trace(other)), "manha", REF)
    assert [d["key"] for d in rep["compared"]["traces"]["diffs"]] == ["agent.run/tool.adjust_campaign_budget#C03"]


def test_retried_agent_task_uses_the_latest_agent_run_in_any_order():
    """Retentativa: dois agent.run no mesmo trace; vale o último, seja qual for a ordem de chegada."""
    first = [rec("agent.run", "a1", "w", "09:00:01", tentativa=1), rec("tool.get_data_health", "t1", "a1", "09:00:02")]
    second = [rec("agent.run", "a2", "w", "09:05:01", tentativa=2), rec("tool.get_data_health", "t2", "a2", "09:05:02")]
    n1 = parity.normalize_trace(first + second)
    n2 = parity.normalize_trace(second + first)
    assert n1 == n2
    assert next(r for r in n1 if r[0] == "agent.run#1")[3]["tentativa"] == 2
