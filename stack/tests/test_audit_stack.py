"""Fase 3 (US3, FR-011, SC-006): o log de auditoria com cadeia de hash continua sendo a prova na trilha stack.

O teste copia o log da sessão para um arquivo próprio antes de adulterar (nunca mexe no da sessão).
"""
from __future__ import annotations

import json
import secrets

import pytest

from agentready import tracing
from agentready_stack import tasks, telemetry

STACK_SPAN_NAMES = {"ingestao.parametros", "contratos.lote", "observabilidade.veredito", "agente.resultado",
                    "fechamento.resumo", "humano.rollback"}


@pytest.fixture
def run_trace(built, monkeypatch):
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "")
    trace_id, span_id = secrets.token_hex(16), secrets.token_hex(8)
    monkeypatch.setenv("TRACEPARENT", f"00-{trace_id}-{span_id}-01")
    token = telemetry.attach_from_env()
    tasks.run_agent("rules")
    tasks.close_run("manual__auditoria")
    tracing.flush()
    yield trace_id
    telemetry.detach(token)


def test_chain_is_intact_and_agent_run_is_still_a_root(run_trace):
    ok, n, msg = tracing.verify_chain()
    assert ok and n > 0 and msg == "cadeia íntegra"
    roots = [t["name"] for t in tracing.tree(tracing.load(run_trace))]
    assert "agent.run" in roots, "o pai (worker.agente.executar) não está no arquivo: agent.run vira raiz"


def test_tampering_is_detected_and_named(run_trace):
    recs = tracing.load()
    target = next(i for i, r in enumerate(recs) if r["trace_id"] == run_trace and r["name"].startswith("tool."))
    recs[target]["attributes"]["adulterado"] = 1.0
    ok, i, msg = tracing.verify_chain(recs)
    assert not ok and i == target
    assert msg == f"registro {target}: conteúdo alterado ({recs[target]['name']})"


def test_stack_spans_never_enter_the_audit_log(run_trace):
    assert not [r for r in tracing.load() if r["name"] in STACK_SPAN_NAMES]
    assert json.dumps(tracing.load(run_trace))  # serializável e presente
