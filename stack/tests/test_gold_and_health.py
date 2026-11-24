"""Gold e saúde das fontes (US3, Blocos 1–2): sem fan-out, frescor POR FEED e
'desconhecido não é zero' chegando ao agente (FR-008, FR-013)."""
from agentready import capabilities as cap
from agentready.db import connect


def test_no_fan_out(con):
    gold = con.execute("SELECT round(SUM(spend_brl), 2) FROM gold.campaign_daily").fetchone()[0]
    silver = con.execute("SELECT round(SUM(spend_brl), 2) FROM silver.ad_spend").fetchone()[0]
    assert gold == silver
    assert con.execute("SELECT COUNT(*) - COUNT(DISTINCT (campaign_id, day)) FROM gold.campaign_daily").fetchone()[0] == 0


def test_freshness_per_feed(con):
    h = {(d, p): s for d, p, s in con.execute('SELECT dataset, "partition", status FROM gold.source_health').fetchall()}
    assert h[("conversions", "meta_capi")] == "stale"
    assert h[("conversions", "ga4")] == "fresh"


def test_stale_feed_yields_null_metrics(con):
    perf = {p["campaign_id"]: p for p in cap.get_campaign_performance(con)}
    for cid in ("C03", "C04"):
        assert perf[cid]["data_status"] == "stale" and perf[cid]["roas"] is None, perf[cid]
        assert perf[cid]["spend"] is not None          # investimento não depende de conversões
    assert perf["C01"]["data_status"] == "fresh" and perf["C01"]["roas"] > 1


def test_backfill_makes_meta_fresh_again(built, dbt):
    from agentready import generate
    c = connect()
    assert generate.backfill_meta(c) > 0
    c.close()
    dbt()
    c = connect()
    try:
        st = c.execute("""SELECT status FROM gold.source_health WHERE dataset='conversions' AND "partition"='meta_capi'""").fetchone()[0]
    finally:
        c.close()
    assert st == "fresh"
