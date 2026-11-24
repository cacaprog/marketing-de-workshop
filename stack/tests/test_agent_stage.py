"""Etapa do agente: idempotência (FR-006, SC-007), retentativa segura e as promessas dos Blocos 1–3."""
from datetime import datetime, timedelta

import pytest

from agentready import autonomy
from agentready.db import connect
from agentready_stack import ledger, tasks


def _changes() -> int:
    c = connect()
    try:
        return c.execute("SELECT COUNT(*) FROM ops.change_log").fetchone()[0]
    finally:
        c.close()


def test_rerun_is_skipped_duplicate(built):
    first = tasks.run_agent()
    n = _changes()
    second = tasks.run_agent()
    assert first["status"] == "done"
    assert second["status"] == "skipped_duplicate"
    assert _changes() == n, "a segunda execução não pode alterar orçamento de novo"


def test_float_noise_in_gold_is_not_a_new_decision(built):
    """Regressão (achado na validação V4): somas paralelas do DuckDB mudam os últimos dígitos a cada
    rebuild. A mesma Gold com ruído de ponto flutuante tem de dar a mesma impressão digital."""
    c = connect()
    try:
        before = ledger.fingerprint(c, "rules", False)
        c.execute("UPDATE gold.campaign_daily SET gross_revenue_brl = gross_revenue_brl + 1e-9, "
                  "spend_brl = spend_brl - 1e-9, discount_brl = discount_brl + 1e-10")
        assert ledger.fingerprint(c, "rules", False) == before
        c.execute("UPDATE gold.campaign_daily SET spend_brl = spend_brl + 1 WHERE campaign_id = 'C01'")
        assert ledger.fingerprint(c, "rules", False) != before, "uma mudança real de R$ 1 tem de contar"
    finally:
        c.close()


def test_changed_run_settings_are_not_duplicates(built):
    assert tasks.run_agent()["status"] == "done"
    c = connect()
    autonomy.set_override(c, "supervised")
    c.close()
    assert tasks.run_agent()["status"] == "done", "mudar a autonomia é uma nova decisão, não repetição"
    assert tasks.run_agent(gullible=True)["status"] == "done", "mudar o modo do agente também"


def _unfinished_run(minutes_ago: int = 5) -> str:
    """Simula uma execução que caiu no meio: linha 'running' com a impressão digital atual."""
    c = connect()
    try:
        fp = ledger.fingerprint(c, "rules", False)
        run_id = ledger.start(c, fp, "dag-run-anterior")
        c.execute("UPDATE ops.agent_runs SET started_at=? WHERE run_id=?",
                  [datetime.now() - timedelta(minutes=minutes_ago), run_id])
        return run_id
    finally:
        c.close()


def test_retry_after_partial_apply_does_not_reapply(built):
    run_id = _unfinished_run()
    c = connect()
    c.execute("""INSERT INTO ops.change_log VALUES ('CHG-antes', 'C02', 'adjust_campaign_budget', 'daily_budget_brl',
                 '5000.0', '5500.0', 'agent', NULL, 'aplicada antes da queda', ?, FALSE)""", [datetime.now()])
    c.close()
    n = _changes()
    with pytest.raises(tasks.PartialApplyError):
        tasks.run_agent()
    assert _changes() == n, "a retentativa não pode reaplicar nada"
    c = connect()
    status = c.execute("SELECT status FROM ops.agent_runs WHERE run_id=?", [run_id]).fetchone()[0]
    c.close()
    assert status == "failed_partial"


def test_retry_after_clean_failure_reruns(built):
    run_id = _unfinished_run()
    assert tasks.run_agent()["status"] == "done"
    c = connect()
    status = c.execute("SELECT status FROM ops.agent_runs WHERE run_id=?", [run_id]).fetchone()[0]
    c.close()
    assert status == "failed"


def test_no_action_on_stale(built):
    out = tasks.run_agent()
    texts = " ".join(s["text"] for s in out["steps"])
    assert "C03 · Não possuo dados atuais" in texts and "C04 · Não possuo dados atuais" in texts
    c = connect()
    meta_changes = c.execute("SELECT COUNT(*) FROM ops.change_log WHERE campaign_id IN ('C03','C04')").fetchone()[0]
    c.close()
    assert meta_changes == 0


def test_gullible_injection_blocked(built):
    out = tasks.run_agent(gullible=True)
    actions = [s["text"] for s in out["steps"] if s["kind"] == "action"]
    injected = [t for t in actions if "C06" in t and "35000" in t]
    assert injected and all("rejected" in t for t in injected), actions
    c = connect()
    budget = c.execute("SELECT daily_budget_brl FROM ops.campaigns WHERE campaign_id='C06'").fetchone()[0]
    c.close()
    assert budget < 35000
