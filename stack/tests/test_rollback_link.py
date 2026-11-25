"""Fase 3 (FR-008): o rollback fica ligado à decisão original (span link + link no Phoenix)."""
from __future__ import annotations

import pytest
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from agentready import tracing
from agentready.db import connect
from agentready_stack import rollback, tasks, telemetry


@pytest.fixture
def spans(monkeypatch):
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "")
    telemetry.reset_for_tests()
    mem = InMemorySpanExporter()
    telemetry.configure(mem)
    yield mem
    telemetry.reset_for_tests()


def _a_change() -> tuple[str, str]:
    c = connect()
    try:
        return c.execute("SELECT change_id, trace_id FROM ops.change_log ORDER BY changed_at LIMIT 1").fetchone()
    finally:
        c.close()


def test_rollback_links_to_the_original_decision(built, spans):
    out = tasks.run_agent()
    assert out["status"] == "done"
    change_id, orig_trace = _a_change()
    res = rollback.run(change_id, actor="instrutor")
    assert res["original_trace_url"] == telemetry.trace_url(orig_trace)
    sp = [s for s in spans.get_finished_spans() if s.name == "humano.rollback"]
    assert len(sp) == 1
    a = dict(sp[0].attributes)
    assert a["change_id"] == change_id and a["actor"] == "instrutor"
    assert a["agentready.original_trace_id"] == orig_trace
    agent_run = next(r for r in tracing.load(orig_trace) if r["name"] == "agent.run")
    assert len(sp[0].links) == 1
    link = sp[0].links[0].context
    assert f"{link.trace_id:032x}" == orig_trace and f"{link.span_id:016x}" == agent_run["span_id"]
    tracing.flush()
    hr = [r for r in tracing.load() if r["name"] == "human.rollback" and r["attributes"].get("change_id") == change_id]
    assert len(hr) == 1
    assert hr[0]["trace_id"] == f"{sp[0].context.trace_id:032x}"
    assert hr[0]["parent_span_id"] == f"{sp[0].context.span_id:016x}"


def test_unknown_change_is_a_clear_error(built, spans):
    with pytest.raises(ValueError, match="não encontrada"):
        rollback.run("CHG-00000000", actor="instrutor")
    assert not [s for s in spans.get_finished_spans() if s.name == "humano.rollback"]


def test_cli_rollback_exit_codes(built, spans, capsys):
    from agentready_stack import cli
    assert cli.main(["rollback", "CHG-00000000", "--by", "instrutor"]) == 1
    assert "FALHA" in capsys.readouterr().err


def test_second_rollback_is_refused_and_records_nothing(built, spans):
    tasks.run_agent()
    change_id, _ = _a_change()
    rollback.run(change_id, actor="instrutor")
    spans.clear()
    with pytest.raises(ValueError, match="já foi revertida"):
        rollback.run(change_id, actor="instrutor")
    assert not [s for s in spans.get_finished_spans() if s.name == "humano.rollback"]
