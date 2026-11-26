"""Fase 4 — relatório de paridade 2.2.0: a Bronze da stack (fontes → dlt) por lote, e o status das cargas."""
import copy
import json
from datetime import datetime
from pathlib import Path

import jsonschema

from agentready_stack import parity

SCHEMA_CANDIDATES = [Path("/opt/agentready/specs/004-stack-ingestion-policy-snapshots/contracts/parity-report.schema.json"),
                     Path(__file__).resolve().parents[2] / "specs/004-stack-ingestion-policy-snapshots/contracts/parity-report.schema.json"]
REF = datetime.now().replace(minute=0, second=0, microsecond=0)


def _schema():
    return json.loads(next(p for p in SCHEMA_CANDIDATES if p.exists()).read_text())


def test_morning_bronze_and_loads_are_identical_and_valid():
    d, s = parity.run_side("default", "manha", REF), parity.run_side("stack", "manha", REF)
    rep = parity.compare_v22(d, s, "manha", REF)
    jsonschema.validate(rep, _schema())
    assert rep["compared"]["bronze"]["items"] > 30 and rep["compared"]["bronze"]["diffs"] == []
    assert rep["compared"]["ingestion"]["items"] == 4 and rep["compared"]["ingestion"]["diffs"] == []
    assert rep["ok"], rep
    # uma diferença na Bronze da stack aparece com tabela|lote, campo e os dois valores
    s2 = copy.deepcopy(s)
    row = next(r for r in s2["bronze"] if r[0] == "conversions" and r[1] != "(colunas)")
    row[2] += 1
    bad = parity.compare_v22(d, s2, "manha", REF)
    diff = bad["compared"]["bronze"]["diffs"][0]
    assert not bad["ok"] and diff["key"] == f"conversions|{row[1]}" and diff["field"] == "rows"
    assert diff["stack_track"] == diff["default_track"] + 1
    s3 = copy.deepcopy(s)
    s3["ingestion"][1] = ["ga4", "falhou", "ga4: fonte indisponível após 4 tentativas (503)"]
    assert parity.compare_v22(d, s3, "manha", REF)["compared"]["ingestion"]["diffs"][0]["key"] == "ga4"
