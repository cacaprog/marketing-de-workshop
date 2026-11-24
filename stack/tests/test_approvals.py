"""Aprovação humana no orquestrador (US4, Bloco 4): FR-016..FR-019, contracts/approval-request.md.

O HITL devolve {chosen_options, params_input, responded_at, responded_by_user}. O desfecho é
aplicado pelo MESMO caminho da trilha padrão (capabilities.decide_approval), que reverifica o
estado vivo. Sem resposta humana = EXPIRADO, e nada é executado (falha segura).
"""
from datetime import datetime, timedelta

import pytest

from agentready import autonomy
from agentready.db import connect, rows
from agentready_stack import approvals, tasks

APPROVER = {"id": "aprovadora", "name": "aprovadora"}


@pytest.fixture
def pending(built):
    """Escada em 'supervised': toda ação do agente vira pedido de aprovação."""
    c = connect()
    autonomy.set_override(c, "supervised")
    c.close()
    out = tasks.run_agent()
    assert out["requests"], "com autonomia supervisionada o agente tem de pedir aprovação"
    return out["requests"]


def _req(request_id):
    c = connect()
    try:
        return rows(c, "SELECT * FROM ops.approval_queue WHERE request_id=?", [request_id])[0]
    finally:
        c.close()


def _budget(cid):
    c = connect()
    try:
        return c.execute("SELECT daily_budget_brl FROM ops.campaigns WHERE campaign_id=?", [cid]).fetchone()[0]
    finally:
        c.close()


def _payload(choice, user=APPROVER, comment="", at=None):
    return {"chosen_options": [choice], "params_input": {"comentario": comment},
            "responded_at": (at or datetime.now()).isoformat(), "responded_by_user": user}


def test_form_shows_what_the_approver_needs(pending):
    r = pending[0]
    form = approvals.to_hitl_kwargs(r)
    assert r["campaign_id"] in form["subject"]
    for text in ("Atual → proposto", "Justificativa do agente", "Por que precisa de você", "| Pré-condição |",
                 r["request_id"], "verificadas de novo no estado vivo"):
        assert text in form["body"], text


def test_approve_executes_and_logs_approver(pending):
    r = next(x for x in pending if x["action"] == "adjust_campaign_budget")
    res = tasks.apply_decision(r["request_id"], _payload(approvals.APPROVE))
    assert res["outcome"] == "executed" and res["decided_by"] == "aprovadora"
    assert _req(r["request_id"])["status"] == "approved"
    assert _budget(r["campaign_id"]) == r["proposed"]
    c = connect()
    actor = c.execute("SELECT actor FROM ops.change_log WHERE change_id=?", [res["change_id"]]).fetchone()[0]
    c.close()
    assert actor == "agent+aprovadora"


def test_approved_change_can_be_rolled_back(pending):
    from agentready import capabilities as cap
    r = next(x for x in pending if x["action"] == "adjust_campaign_budget")
    res = tasks.apply_decision(r["request_id"], _payload(approvals.APPROVE))
    c = connect()
    cap.rollback(c, res["change_id"], "instrutor")
    c.close()
    assert _budget(r["campaign_id"]) == r["current"]


def test_reject_changes_nothing(pending):
    r = pending[0]
    before = _budget(r["campaign_id"])
    res = tasks.apply_decision(r["request_id"], _payload(approvals.REJECT))
    assert res["outcome"] == "rejected" and res["decided_by"] == "aprovadora"
    assert _req(r["request_id"])["status"] == "rejected"
    assert _budget(r["campaign_id"]) == before


def test_timeout_is_expired(pending):
    """Timeout com defaults=["Rejeitar"]: o provider devolve a opção padrão SEM usuário."""
    r = pending[0]
    before = _budget(r["campaign_id"])
    res = tasks.apply_decision(r["request_id"], _payload(approvals.REJECT, user=None))
    assert res["outcome"] == "expired" and res["decided_by"] == "sistema:timeout"
    q = _req(r["request_id"])
    assert q["status"] == "expired" and q["decided_by"] == "sistema:timeout"
    assert _budget(r["campaign_id"]) == before


def test_answer_after_the_deadline_is_expired(pending):
    r = pending[0]
    deadline = datetime.now()
    res = tasks.apply_decision(r["request_id"], _payload(approvals.APPROVE, at=deadline + timedelta(minutes=1)),
                               timeout_at=deadline.isoformat())
    assert res["outcome"] == "expired"


def test_failed_hitl_task_is_expired(pending):
    """Tarefa HITL falhou (ex.: HITLTimeoutError sem defaults): nenhum payload chega."""
    r = pending[0]
    before = _budget(r["campaign_id"])
    assert tasks.apply_decision(r["request_id"], None)["outcome"] == "expired"
    assert _budget(r["campaign_id"]) == before


def test_approved_but_state_changed_is_rejected_live_recheck(pending):
    r = next(x for x in pending if x["action"] == "adjust_campaign_budget")
    c = connect()
    c.execute("UPDATE ops.campaigns SET locked_by_human=TRUE WHERE campaign_id=?", [r["campaign_id"]])
    c.close()
    before = _budget(r["campaign_id"])
    res = tasks.apply_decision(r["request_id"], _payload(approvals.APPROVE))
    assert res["outcome"] == "rejected_live_recheck"
    assert _budget(r["campaign_id"]) == before


def test_request_leaves_pending_once(pending):
    r = next(x for x in pending if x["action"] == "adjust_campaign_budget")
    first = tasks.apply_decision(r["request_id"], _payload(approvals.APPROVE))
    second = tasks.apply_decision(r["request_id"], _payload(approvals.APPROVE))
    assert first["outcome"] == "executed"
    assert second["outcome"] == "already_decided"
    c = connect()
    n = c.execute("SELECT COUNT(*) FROM ops.change_log WHERE campaign_id=? AND actor='agent+aprovadora'",
                  [r["campaign_id"]]).fetchone()[0]
    c.close()
    assert n == 1


def test_comment_is_recorded(pending):
    r = pending[0]
    tasks.apply_decision(r["request_id"], _payload(approvals.REJECT, comment="aguardar fim do mês"))
    assert "comentário de aprovadora: aguardar fim do mês" in _req(r["request_id"])["reason"]
