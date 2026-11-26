"""Fase 4 (FR-016, SC-007) — sem política, nenhuma escrita: OPA fora do ar, lento, com erro ou com resposta fora do
contrato nega a ação (e nunca trava); antes do agente, o preflight impede a execução."""
import json
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from agentready import capabilities
from agentready.db import connect

EVAL = "agentready_stack.policy_opa:OpaEvaluator"


def _server(handler):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


def _handler(status=200, body=None, delay=0.0):
    class H(BaseHTTPRequestHandler):
        def _reply(self):
            time.sleep(delay)
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(body if body is not None else {}).encode())

        do_GET = do_POST = _reply

        def log_message(self, *a):
            pass
    return H


def _closed_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return f"http://127.0.0.1:{p}"


BAD = {"fora do ar": None, "lento": _handler(delay=5), "erro 500": _handler(status=500),
       "id desconhecido": _handler(body={"result": {"permitido": True, "versao": "1", "checagens": [{"id": "x", "ok": True}]}}),
       "sem resultado": _handler(body={})}


@pytest.mark.parametrize("kind", list(BAD))
def test_write_is_denied_and_nothing_changes(built, monkeypatch, kind):
    srv = None
    if BAD[kind] is None:
        url = _closed_port()
    else:
        srv, url = _server(BAD[kind])
    monkeypatch.setenv("AGENTREADY_POLICY_EVALUATOR", EVAL)
    monkeypatch.setenv("OPA_URL", url)
    c = connect()
    try:
        before = c.execute("SELECT daily_budget_brl FROM ops.campaigns WHERE campaign_id='C01'").fetchone()[0]
        t0 = time.time()
        r = capabilities.adjust_campaign_budget(c, "C01", before * 1.1, "subir ROAS")
        assert time.time() - t0 < 2.5, "nunca trava: 2 s de limite e nenhuma nova tentativa"
        assert r.status == "rejected" and [p.id for p in r.preconditions] == ["politica_avaliada"]
        assert "não foi possível avaliar a política" in r.preconditions[0].detail
        assert c.execute("SELECT daily_budget_brl FROM ops.campaigns WHERE campaign_id='C01'").fetchone()[0] == before
        assert c.execute("SELECT count(*) FROM ops.change_log").fetchone()[0] == 0
        # leitura não pergunta à política
        assert capabilities.get_data_health(c)["stale_sources"] is not None
    finally:
        c.close()
        if srv:
            srv.shutdown()


def test_an_approved_request_is_rechecked_and_denied_when_the_policy_is_down(built, monkeypatch):
    from agentready import autonomy
    c = connect()
    try:
        autonomy.set_override(c, "supervised")
        r = capabilities.adjust_campaign_budget(c, "C01", 4400.0, "subir ROAS")
        assert r.status == "queued_for_approval", r.message
        monkeypatch.setenv("AGENTREADY_POLICY_EVALUATOR", EVAL)
        monkeypatch.setenv("OPA_URL", _closed_port())
        res = capabilities.decide_approval(c, r.request_id, "aprovadora", True)
        assert getattr(res, "status", None) == "rejected"
        assert c.execute("SELECT count(*) FROM ops.change_log").fetchone()[0] == 0
    finally:
        c.close()


def test_preflight_stops_the_agent_before_it_reads_anything(built, monkeypatch):
    from agentready_stack import tasks
    monkeypatch.setenv("AGENTREADY_POLICY_EVALUATOR", EVAL)
    monkeypatch.setenv("OPA_URL", _closed_port())
    with pytest.raises(tasks.PolicyUnavailableError, match="política indisponível ou inválida"):
        tasks.run_agent("rules", False, "sem-politica")
    c = connect()
    try:
        has = c.execute("SELECT count(*) FROM information_schema.tables WHERE table_catalog='ops' "
                        "AND table_name='agent_runs'").fetchone()[0]
        assert not has or c.execute("SELECT count(*) FROM ops.agent_runs WHERE dag_run_id='sem-politica'").fetchone()[0] == 0
    finally:
        c.close()
