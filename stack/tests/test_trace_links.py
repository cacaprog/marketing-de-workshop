"""Fase 3: links para o Phoenix (contracts/trace-links.md)."""
from __future__ import annotations

from agentready_stack import telemetry


def test_trace_url(monkeypatch):
    monkeypatch.delenv("PHOENIX_PORT", raising=False)
    assert telemetry.trace_url("abc") == "http://localhost:6006/redirects/traces/abc"
    assert telemetry.trace_url(None) is None


def test_trace_url_honors_port(monkeypatch):
    monkeypatch.setenv("PHOENIX_PORT", "7000")
    assert telemetry.trace_url("abc") == "http://localhost:7000/redirects/traces/abc"


def test_span_url(monkeypatch):
    monkeypatch.delenv("PHOENIX_PORT", raising=False)
    assert telemetry.span_url("def") == "http://localhost:6006/redirects/spans/def"
    assert telemetry.span_url(None) is None


# ------------------------------------------------------------------ US2 (T023)

DETAILS = {"request_id": "REQ-12345678", "action": "adjust_campaign_budget", "campaign_id": "C01",
           "campaign_name": "Google Marca", "current": 1000.0, "proposed": 1200.0, "justification": "ROAS alto",
           "checks": [{"id": "dados_frescos", "passed": True, "detail": "ok"}], "autonomy_reasons": ["acima de 10%"],
           "trace_id": "ab" * 16}


def test_approval_form_links_to_the_trace(monkeypatch):
    from agentready_stack import approvals
    monkeypatch.delenv("PHOENIX_PORT", raising=False)
    body = approvals.to_hitl_kwargs(DETAILS)["body"].splitlines()
    i = next(n for n, line in enumerate(body) if line.startswith("Trace: "))
    assert body[i + 1] == f"[Abrir o raciocínio do agente no Phoenix](http://localhost:6006/redirects/traces/{'ab' * 16})"


def test_approval_form_without_trace_has_no_link():
    from agentready_stack import approvals
    body = approvals.to_hitl_kwargs(DETAILS | {"trace_id": None})["body"]
    assert "Phoenix" not in body


def test_decisions_rows_carry_trace_url(built):
    from agentready_stack import incidents_cli, tasks
    tasks.run_agent()
    out = incidents_cli.decisions_since("00:00")
    assert out["decisions"] and all("trace_url" in d for d in out["decisions"])
    assert all(d["trace_url"] == telemetry.trace_url(d["trace_id"]) for d in out["decisions"])
