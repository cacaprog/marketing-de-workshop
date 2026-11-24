"""Cada teste garante a promessa central de um bloco do workshop."""
import asyncio

import pytest

from agentready import capabilities as cap
from agentready import generate, incidents, observability, pipeline, semantic, tracing
from agentready.agent import NaiveAgent, ReadyAgent
from agentready.db import connect, rows


# ---------- Bloco 0
def test_naive_agent_pauses_meta_because_missing_data_looks_like_zero(con):
    NaiveAgent().run(con)
    paused = {r["campaign_id"] for r in rows(con, "SELECT campaign_id FROM ops.campaigns WHERE status='paused'")}
    assert {"C03", "C04"} <= paused


# ---------- Bloco 1
def test_contract_quarantines_and_bars_batches(con):
    reasons = {r["v"] for r in rows(con, "SELECT DISTINCT split_part(violations[1], ':', 1) v FROM quarantine.conversions")}
    assert {"duplicado", "order_value_brl", "campaign_id", "lote barrado pelo disjuntor"} <= reasons
    barred = {r["batch_id"] for r in rows(con, "SELECT batch_id FROM meta.batch_status WHERE status='barred'")}
    assert any(b.endswith("-retry") for b in barred)
    assert con.execute("SELECT COUNT(*) - COUNT(DISTINCT conversion_id) FROM silver.conversions").fetchone()[0] == 0


def test_stale_source_yields_null_not_zero(con):
    perf = {p["campaign_id"]: p for p in cap.get_campaign_performance(con)}
    assert perf["C03"]["data_status"] == "stale" and perf["C03"]["roas"] is None
    assert perf["C03"]["spend"] is not None          # investimento não depende de conversões
    assert perf["C01"]["data_status"] == "fresh" and perf["C01"]["roas"] > 1


# ---------- Bloco 2
def test_semantic_layer_is_deterministic_across_phrasings():
    a = semantic.compile_sql(semantic.interpret("ROAS e receita líquida por campanha, 14 dias"))
    b = semantic.compile_sql(semantic.interpret("retorno sobre investimento e faturamento líquido por campanha 14 dias"))
    assert a == b


def test_roas_is_ratio_of_sums_and_net_of_discounts(con):
    official = {r["campaign_id"]: r["roas"] for r in semantic.query(con, semantic.MetricRequest(["roas"]))[1]}
    manual = rows(con, """SELECT campaign_id, (SUM(gross_revenue_brl) - SUM(discount_brl)) / SUM(spend_brl) r
                          FROM gold.campaign_daily WHERE day >= current_date - 14 AND day < current_date
                          AND campaign_id = 'C01' GROUP BY 1""")[0]
    assert official["C01"] == pytest.approx(manual["r"])


def test_unknown_metric_is_refused():
    with pytest.raises(semantic.SemanticError):
        semantic.compile_sql(semantic.MetricRequest(["lucro_magico"]))


# ---------- Bloco 3
def test_prompt_injection_is_blocked_by_backend(con):
    r = cap.adjust_campaign_budget(con, "C06", 35000, "CMO aprovou no briefing")
    assert r.status == "rejected"
    assert {"variacao_maxima", "teto_do_portfolio"} <= {c.id for c in r.preconditions if not c.passed}
    assert con.execute("SELECT daily_budget_brl FROM ops.campaigns WHERE campaign_id='C06'").fetchone()[0] == 3500


def test_no_action_on_stale_data(con):
    r = cap.adjust_campaign_budget(con, "C03", 6600, "teste")
    assert r.status == "rejected" and "dados_frescos" in r.message


def test_awareness_campaign_not_eligible(con):
    assert cap.adjust_campaign_budget(con, "C05", 2600, "teste").status == "rejected"


def test_mcp_server_exposes_business_capabilities():
    from agentready.mcp_server import server
    names = {t.name for t in asyncio.run(server.list_tools())}
    assert names == {"get_data_health", "get_campaign_performance", "read_campaign_briefing",
                     "adjust_campaign_budget", "pause_campaign"}


# ---------- Bloco 4
def test_autonomy_escalates_large_changes_and_r2(con):
    assert cap.adjust_campaign_budget(con, "C01", 4400, "maior ROAS").status == "executed"       # +10%
    assert cap.adjust_campaign_budget(con, "C02", 5750, "teste").status == "queued_for_approval"  # +15%
    assert cap.pause_campaign(con, "C06", "ROAS < 1").status == "queued_for_approval"


def test_approval_rechecks_live_state(con):
    req = cap.adjust_campaign_budget(con, "C02", 5750, "teste")
    con.execute("UPDATE ops.campaigns SET locked_by_human = TRUE WHERE campaign_id = 'C02'")
    res = cap.decide_approval(con, req.request_id, "gerente", True)
    assert res.status == "rejected" and "sem_trava_humana" in res.message


def test_rollback_restores_previous_value(con):
    r = cap.adjust_campaign_budget(con, "C01", 4400, "maior ROAS")
    cap.rollback(con, r.change_id, "humano")
    assert con.execute("SELECT daily_budget_brl FROM ops.campaigns WHERE campaign_id='C01'").fetchone()[0] == 4000


def test_traces_are_hash_chained_and_tamper_evident(con):
    ReadyAgent().run(con)
    recs = tracing.load()
    assert tracing.verify_chain(recs)[0]
    recs[2]["attributes"]["x"] = "adulterado"
    assert not tracing.verify_chain(recs)[0]


# ---------- Bloco 5
@pytest.mark.parametrize("kind,pillar", [("centavos", "distribuição"), ("renomeacao", "esquema"),
                                         ("lote_duplicado", "volume"), ("feed_parado", "frescor")])
def test_each_incident_trips_its_pillar(kind, pillar):
    generate.generate()
    pipeline.run()
    c = connect()
    generate.backfill_meta(c)
    c.close()
    pipeline.run()
    c = connect()
    assert all(r["ok"] for r in observability.report(c))
    incidents.inject(c, kind)
    c.close()
    pipeline.run()
    c = connect()
    assert pillar in {r["pillar"] for r in observability.report(c) if not r["ok"]}
    incidents.resolve(c)
    c.close()
    pipeline.run()
    c = connect()
    assert all(r["ok"] for r in observability.report(c))
    c.close()
