"""Fase 3: spans da trilha stack (contracts/span-catalog.md) e ligação do agente ao trace da execução.

Usa um exportador em memória no tracer da stack. O log de auditoria (agentready.tracing) é o arquivo
temporário da sessão (conftest), então cada teste filtra pelo trace_id que ele mesmo injeta.
"""
from __future__ import annotations

import json
import os
import secrets
import time

import pytest
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode

from agentready import tracing
from agentready_stack import telemetry

STACK_SPAN_NAMES = {"ingestao.parametros", "contratos.lote", "observabilidade.veredito", "agente.resultado",
                    "fechamento.resumo", "humano.rollback"}


@pytest.fixture
def spans(monkeypatch):
    """Exportador em memória no tracer da stack; sem envio OTLP."""
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "")
    telemetry.reset_for_tests()
    mem = InMemorySpanExporter()
    telemetry.configure(mem)
    yield mem
    telemetry.reset_for_tests()


@pytest.fixture
def parent(monkeypatch):
    """Um TRACEPARENT como o que o DAG injeta: devolve (trace_id, span_id) e desfaz o attach no fim."""
    trace_id, span_id = secrets.token_hex(16), secrets.token_hex(8)
    monkeypatch.setenv("TRACEPARENT", f"00-{trace_id}-{span_id}-01")
    token = telemetry.attach_from_env()
    assert token is not None
    yield trace_id, span_id
    telemetry.detach(token)


def by_name(mem: InMemorySpanExporter, name: str) -> list:
    return [s for s in mem.get_finished_spans() if s.name == name]


def audit(trace_id: str) -> list[dict]:
    tracing.flush()
    return tracing.load(trace_id)


# ------------------------------------------------------------------ fundação (T009)

def test_agent_span_joins_the_injected_trace(parent):
    trace_id, span_id = parent
    with tracing.span("x.teste_fase3"):
        pass
    recs = [r for r in audit(trace_id) if r["name"] == "x.teste_fase3"]
    assert len(recs) == 1
    assert recs[0]["trace_id"] == trace_id
    assert recs[0]["parent_span_id"] == span_id


def test_stack_spans_are_exported_but_never_audited(spans, parent):
    trace_id, _ = parent
    with telemetry.span("contratos.lote", batch_id="b1"):
        pass
    assert len(by_name(spans, "contratos.lote")) == 1
    assert by_name(spans, "contratos.lote")[0].context.trace_id == int(trace_id, 16)
    assert not [r for r in audit(trace_id) if r["name"] in STACK_SPAN_NAMES]


def test_no_traceparent_is_a_noop(monkeypatch):
    monkeypatch.delenv("TRACEPARENT", raising=False)
    assert telemetry.attach_from_env() is None
    monkeypatch.setenv("TRACEPARENT", "lixo")
    assert telemetry.attach_from_env() is None


def test_unknown_values_are_omitted_not_zero(spans):
    with telemetry.span("observabilidade.veredito", ratio=None, observed=0.0, pillar="distribuicao"):
        pass
    attrs = dict(by_name(spans, "observabilidade.veredito")[0].attributes)
    assert "ratio" not in attrs
    assert attrs["observed"] == 0.0 and attrs["pillar"] == "distribuicao"


def test_error_status_carries_message(spans):
    with telemetry.span("contratos.lote", error="lote b1 barrado: quarentena 40,0% > limite 5%"):
        pass
    st = by_name(spans, "contratos.lote")[0].status
    assert st.status_code == StatusCode.ERROR and st.description.startswith("lote b1 barrado")


def test_flush_never_raises_when_collector_is_down(monkeypatch):
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://127.0.0.1:9")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_TIMEOUT", "1")
    telemetry.reset_for_tests()
    try:
        with telemetry.span("fechamento.resumo"):
            pass
        t0 = time.monotonic()
        telemetry.flush()
        assert time.monotonic() - t0 < 5
    finally:
        telemetry.reset_for_tests()


def test_common_attrs_shape():
    a = telemetry.common_attrs("manual__x", "2026-11-25", None)
    assert a == {"airflow.dag_run.run_id": "manual__x", "agentready.business_date": "2026-11-25",
                 "agentready.incident": "nenhum"}
    assert json.loads(json.dumps(a))  # serializável
    assert os.environ.get("AGENTREADY_TRACES")  # conftest isolou o log de auditoria


# ------------------------------------------------------------------ US1: o agente dentro do trace da execução (T015)

def test_run_agent_lands_in_the_run_trace(built, spans, parent):
    from agentready_stack import tasks
    trace_id, span_id = parent
    out = tasks.run_agent("rules", dag_run_id="manual__fase3")
    assert out["status"] == "done"
    assert out["trace_id"] == trace_id
    assert out["trace_url"] == telemetry.trace_url(trace_id)
    roots = [r for r in audit(trace_id) if r["name"] == "agent.run"]
    assert len(roots) == 1 and roots[0]["parent_span_id"] == span_id
    res = by_name(spans, "agente.resultado")
    assert len(res) == 1
    a = dict(res[0].attributes)
    assert a["agentready.status"] == "done"
    assert a["agentready.trace_url"] == out["trace_url"]
    assert json.loads(a["agentready.request_ids"]) == [r["request_id"] for r in out["requests"]]
    assert a["airflow.dag_run.run_id"] == "manual__fase3"


def test_duplicate_run_has_no_trace_and_says_why(built, spans, parent):
    from agentready_stack import tasks
    trace_id, _ = parent
    tasks.run_agent("rules")
    n_agent = len([r for r in audit(trace_id) if r["name"] == "agent.run"])
    spans.clear()
    out = tasks.run_agent("rules")
    assert out["status"] == "skipped_duplicate" and out["trace_url"] is None
    res = by_name(spans, "agente.resultado")
    assert dict(res[0].attributes)["agentready.status"] == "skipped_duplicate"
    assert [e.name for e in res[0].events] == ["sem trace: já decidido para estes dados"]
    assert len([r for r in audit(trace_id) if r["name"] == "agent.run"]) == n_agent, "pulado: nenhum agent.run novo"


# ------------------------------------------------------------------ US2: spans de domínio (T022)

def test_barred_batch_is_an_error_span(run_incident, spans):
    from agentready_stack import tasks
    run_incident("lote_duplicado")
    with pytest.raises(tasks.QualityAlert):
        tasks.quality_alert()
    lotes = by_name(spans, "contratos.lote")
    assert lotes, "um span por lote desde a marca d'água (spans terminam antes da exceção)"
    barred = [s for s in lotes if dict(s.attributes)["batch.status"] == "barred"]
    passed = [s for s in lotes if dict(s.attributes)["batch.status"] == "passed"]
    assert barred and passed
    b = barred[0]
    a = dict(b.attributes)
    assert b.status.status_code == StatusCode.ERROR
    assert b.status.description.startswith(f"lote {a['batch_id']} barrado: quarentena")
    for k in ("contract", "batch_id", "rows", "quarantined_rows", "quarantine_rate", "max_quarantine_rate", "barred_by"):
        assert k in a, k
    for s in passed:
        assert s.status.status_code != StatusCode.ERROR and "barred_by" not in dict(s.attributes)


def test_failed_distribution_verdict_is_an_error_span(run_incident, spans):
    from agentready_stack import tasks
    from agentready_stack.observe import ObservabilityAlert
    run_incident("centavos")
    with pytest.raises(ObservabilityAlert):
        tasks.observe()
    vs = by_name(spans, "observabilidade.veredito")
    dist = [s for s in vs if dict(s.attributes)["pillar"].startswith("distribui")
            and dict(s.attributes)["agentready.status"] == "fail"]
    assert dist, [dict(s.attributes) for s in vs]
    a = dict(dist[0].attributes)
    assert dist[0].status.status_code == StatusCode.ERROR
    assert {"ratio", "observed", "baseline"} <= set(a)


def test_short_history_warn_is_ok_and_unknowns_are_omitted(short_history, dbt, spans):
    from agentready_stack import tasks
    from agentready_stack.observe import ObservabilityAlert
    dbt()
    try:
        tasks.observe()
    except ObservabilityAlert:
        pass  # a Meta parada falha o frescor; aqui só importa o aviso de histórico
    from agentready.db import connect
    from agentready_stack import observe as obs
    c = connect()
    try:
        rows_ = {(v["pillar"], v["target"]): v for v in obs.verdicts(c)}
    finally:
        c.close()
    vs = by_name(spans, "observabilidade.veredito")
    warns = [s for s in vs if dict(s.attributes)["agentready.status"] == "histórico insuficiente"]
    assert warns
    for s in warns:
        assert s.status.status_code != StatusCode.ERROR, "aviso nunca é erro"
    for s in vs:                                  # NULL na tabela de vereditos = atributo AUSENTE, nunca 0
        a = dict(s.attributes)
        row = rows_[(a["pillar"], a["target"])]
        for k in ("observed", "baseline", "ratio"):
            assert (k in a) == (row[k] is not None), (a["pillar"], a["target"], k)


@pytest.mark.parametrize("incident", ["nenhum", "aleatorio"])
def test_ingest_span_records_parameters(built, spans, monkeypatch, incident):
    from agentready_stack import tasks
    monkeypatch.setattr("agentready.incidents.inject", lambda con, kind: {"incident_id": "INC-teste"})
    tasks.ingest({"incident": incident}, "manual__fase3")
    a = dict(by_name(spans, "ingestao.parametros")[0].attributes)
    assert a["agentready.incident"] == incident, "aleatorio continua aleatorio (não revela o tipo)"
    assert a["agentready.breaker.source"] == "compartilhado" and isinstance(a["agentready.breaker.value"], bool)
    assert a["airflow.dag_run.run_id"] == "manual__fase3"


def test_approval_and_expiry_land_in_the_run_trace(built, spans, parent):
    from agentready import autonomy
    from agentready.db import connect
    from agentready_stack import tasks
    trace_id, _ = parent
    c = connect()
    autonomy.set_override(c, "supervised")
    c.close()
    reqs = tasks.run_agent()["requests"]
    assert len(reqs) >= 2
    from datetime import datetime
    tasks.apply_decision(reqs[0]["request_id"], {"chosen_options": ["Aprovar"], "params_input": {},
                                                 "responded_at": datetime.now().isoformat(),
                                                 "responded_by_user": {"id": "aprovadora", "name": "aprovadora"}})
    tasks.apply_decision(reqs[1]["request_id"], None)
    names = [r["name"] for r in audit(trace_id)]
    assert "human.approval" in names and "human.approval_expired" in names


def test_close_emits_summary(built, spans):
    from agentready_stack import tasks
    tasks.close_run("manual__fase3")
    a = dict(by_name(spans, "fechamento.resumo")[0].attributes)
    assert isinstance(json.loads(a["stale_sources"]), list) and "pending_requests" in a


def test_spans_never_carry_the_api_key(built, spans, parent, monkeypatch):
    """Caso de borda (spec): spans não levam credenciais."""
    from agentready_stack import tasks
    secret = "sk-ant-teste-" + secrets.token_hex(8)
    monkeypatch.setenv("ANTHROPIC_API_KEY", secret)
    trace_id, _ = parent
    tasks.run_agent("rules")
    tasks.close_run("manual__fase3")
    blob = json.dumps([dict(s.attributes) for s in spans.get_finished_spans()], default=str)
    blob += json.dumps(audit(trace_id), default=str)
    assert secret not in blob


# ------------------------------------------------------------------ US3: Phoenix fora do ar (T034)

def test_phoenix_check_never_raises_and_says_why(monkeypatch):
    monkeypatch.setenv("PHOENIX_INTERNAL_URL", "http://127.0.0.1:9")
    monkeypatch.setenv("OTEL_COLLECTOR_HEALTH_URL", "http://127.0.0.1:9/")
    t0 = time.monotonic()
    r = telemetry.phoenix_has_trace("ab" * 16, attempts=2, wait_s=0.1, timeout=1)
    assert time.monotonic() - t0 < 5
    assert r["ok"] is False and r["reason"].startswith("coletor fora do ar")
    assert r["url"] == telemetry.trace_url("ab" * 16)


def test_close_run_warns_when_phoenix_is_unreachable(built, spans, parent, monkeypatch, capsys):
    from agentready_stack import tasks
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://127.0.0.1:9")   # liga a checagem
    monkeypatch.setenv("PHOENIX_INTERNAL_URL", "http://127.0.0.1:9")
    monkeypatch.setenv("OTEL_COLLECTOR_HEALTH_URL", "http://127.0.0.1:9/")
    monkeypatch.setattr(telemetry, "phoenix_has_trace",
                        lambda tid, **kw: {"ok": False, "reason": "coletor fora do ar; teste", "url": telemetry.trace_url(tid)})
    tasks.run_agent("rules", dag_run_id="manual__fase3")
    out = tasks.close_run("manual__fase3")
    assert out["traces"]["ok"] is False
    printed = capsys.readouterr().out
    assert "ainda não está no Phoenix" in printed and "make auditoria" in printed
    a = dict(by_name(spans, "fechamento.resumo")[0].attributes)
    assert a["traces.ok"] is False


def test_collector_down_is_named_even_when_phoenix_answers(monkeypatch):
    """Achado do make test-live (execução E): Phoenix no ar + coletor parado = o motivo é o coletor."""
    monkeypatch.setattr(telemetry, "_post_json", lambda url, body, timeout: {"data": {"getTraceByOtelId": None}})
    monkeypatch.setattr(telemetry, "collector_up", lambda timeout=2: False)
    r = telemetry.phoenix_has_trace("cd" * 16, attempts=1, wait_s=0)
    assert r["ok"] is False and r["reason"].startswith("coletor fora do ar")
    monkeypatch.setattr(telemetry, "collector_up", lambda timeout=2: True)
    assert telemetry.phoenix_has_trace("cd" * 16, attempts=1, wait_s=0)["reason"].startswith("o Phoenix responde")


def test_trace_without_agent_run_is_not_ok(monkeypatch):
    """Achado da revisão: o trace da execução pode existir (spans do pipeline) sem a árvore do agente."""
    only_pipeline = {"data": {"getTraceByOtelId": {"spans": {"edges": [{"node": {"name": "contratos.lote"}},
                                                                    {"node": {"name": "worker.agente.executar"}}]}}}}
    monkeypatch.setattr(telemetry, "_post_json", lambda url, body, timeout: only_pipeline)
    monkeypatch.setattr(telemetry, "collector_up", lambda timeout=2: True)
    r = telemetry.phoenix_has_trace("ef" * 16, attempts=1, wait_s=0)
    assert r["ok"] is False and "árvore do agente" in r["reason"]
    with_agent = {"data": {"getTraceByOtelId": {"spans": {"edges": [{"node": {"name": "agent.run"}}]}}}}
    monkeypatch.setattr(telemetry, "_post_json", lambda url, body, timeout: with_agent)
    assert telemetry.phoenix_has_trace("ef" * 16, attempts=1, wait_s=0)["ok"] is True


def test_export_warning_goes_to_stderr(capsys):
    """Achado da revisão: o stdout termina com o JSON que o DAG lê; aviso de exportação vai para o stderr."""
    class Boom:
        def export(self, spans):
            raise ConnectionError("coletor caiu")
    telemetry._warned = False
    telemetry._QuietExporter(Boom()).export([])
    out = capsys.readouterr()
    assert out.out == "" and "traces da stack não enviados" in out.err


def test_span_start_failure_never_breaks_the_task(monkeypatch):
    """Achado da revisão: o span só nasce no __enter__; uma falha ali vira span inerte, a tarefa segue."""
    class BrokenTracer:
        def start_as_current_span(self, *a, **k):
            class CM:
                def __enter__(self):
                    raise RuntimeError("processador quebrado")
                def __exit__(self, *e):
                    return False
            return CM()

    class BrokenProvider:
        def get_tracer(self, *a, **k):
            return BrokenTracer()
    monkeypatch.setattr(telemetry, "_get_provider", lambda: BrokenProvider())
    ran = []
    with telemetry.span("contratos.lote", batch_id="b1") as sp:
        ran.append(sp)
    assert ran and not ran[0].get_span_context().is_valid


def test_exception_in_the_block_still_propagates(spans):
    with pytest.raises(ValueError):
        with telemetry.span("observabilidade.veredito"):
            raise ValueError("falha da própria tarefa")
    assert by_name(spans, "observabilidade.veredito"), "o span termina e é exportado mesmo com a exceção"



# ------------------------------------------------------------------ achado da validação ao vivo (V-P3-7)

@pytest.mark.parametrize("choice,outcome", [("Aprovar", "executed"), ("Rejeitar", "rejected"), (None, "expired")])
def test_every_human_decision_is_a_span_in_the_run_trace(built, spans, parent, choice, outcome):
    """A rejeição não deixava span: `humano.decisao` registra todos os desfechos no trace da execução."""
    from datetime import datetime

    from agentready import autonomy
    from agentready.db import connect
    from agentready_stack import tasks
    trace_id, _ = parent
    c = connect()
    autonomy.set_override(c, "supervised")
    c.close()
    req = next(r for r in tasks.run_agent()["requests"] if r["action"] == "adjust_campaign_budget")
    payload = None if choice is None else {
        "chosen_options": [choice], "params_input": {"comentario": "teste"}, "responded_at": datetime.now().isoformat(),
        "responded_by_user": {"id": "aprovadora", "name": "aprovadora"}}
    res = tasks.apply_decision(req["request_id"], payload)
    assert res["outcome"] == outcome
    dec = by_name(spans, "humano.decisao")
    assert len(dec) == 1
    a = dict(dec[0].attributes)
    assert dec[0].context.trace_id == int(trace_id, 16)
    assert a["request_id"] == req["request_id"] and a["agentready.outcome"] == outcome
    assert a["decided_by"] == ("sistema:timeout" if choice is None else "aprovadora")
    if choice is not None:
        assert a["comment"] == "teste"
    if outcome == "executed":
        child = [r for r in audit(trace_id) if r["name"] == "human.approval"]
        assert child and child[-1]["parent_span_id"] == f"{dec[0].context.span_id:016x}"
