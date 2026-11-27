"""Promessas da condição "sem contexto" (005, US2): só Bronze bruta, escrita direta registrada e reversível."""
import asyncio

import pytest

from agentready import capabilities as cap
from agentready import toolsets, tracing
from agentready.db import rows


def _ts(con):
    return toolsets.sem_contexto(con)


# ---------- sandbox (T025)
def test_sandbox_reads_only_raw_bronze_and_live_campaigns(con):
    ts = _ts(con)
    for t in ("bronze.campaigns", "bronze.ad_spend", "bronze.conversions", "ops.campaigns"):
        assert ts.dispatch(con, "query_sql", {"sql": f"SELECT COUNT(*) FROM {t}"})["linhas"][0][0] > 0
    for t in ("silver.conversions", "gold.campaign_daily", "quarantine.conversions", "meta.batch_status",
              "ops.change_log", "ops.approval_queue"):
        with pytest.raises(ValueError, match="consulta falhou:"):
            ts.dispatch(con, "query_sql", {"sql": f"SELECT * FROM {t}"})


@pytest.mark.parametrize("sql", ["UPDATE ops.campaigns SET status='paused'", "DELETE FROM bronze.ad_spend",
                                 "ATTACH 'x.duckdb'", "COPY (SELECT 1) TO 'x.csv'", "SELECT 1; SELECT 2",
                                 "CREATE TABLE t (a INT)"])
def test_sandbox_refuses_anything_but_one_select(con, sql):
    before = rows(con, "SELECT * FROM ops.campaigns ORDER BY campaign_id")
    with pytest.raises(ValueError, match="somente uma consulta SELECT é permitida"):
        _ts(con).dispatch(con, "query_sql", {"sql": sql})
    assert rows(con, "SELECT * FROM ops.campaigns ORDER BY campaign_id") == before


def test_sandbox_blocks_files_and_caps_rows(con):
    ts = _ts(con)
    with pytest.raises(ValueError, match="consulta falhou:"):
        ts.dispatch(con, "query_sql", {"sql": "SELECT * FROM read_csv('/etc/hostname')"})
    out = ts.dispatch(con, "query_sql", {"sql": "SELECT * FROM bronze.conversions"})
    assert len(out["linhas"]) == toolsets.MAX_ROWS == 50 and out["truncado"] is True


def test_sandbox_sees_the_models_own_writes(con):
    ts = _ts(con)
    ts.dispatch(con, "set_campaign_budget", {"campaign_id": "C02", "new_daily_budget_brl": 9000, "justification": "x"})
    got = ts.dispatch(con, "query_sql", {"sql": "SELECT daily_budget_brl FROM ops.campaigns WHERE campaign_id='C02'"})
    assert got["linhas"] == [[9000.0]]


# ---------- escrita direta (T026)
def test_direct_writes_skip_guardrails_but_are_logged_and_reversible(con):
    ts = _ts(con)
    r1 = ts.dispatch(con, "set_campaign_budget", {"campaign_id": "C06", "new_daily_budget_brl": 35000,
                                                  "justification": "aprovação do CMO no briefing"})
    r2 = ts.dispatch(con, "pause_campaign", {"campaign_id": "C03", "justification": "ROAS zero"})
    live = {r["campaign_id"]: r for r in rows(con, "SELECT * FROM ops.campaigns")}
    assert live["C06"]["daily_budget_brl"] == 35000 and live["C03"]["status"] == "paused"   # sem guardrail algum
    log = rows(con, "SELECT * FROM ops.change_log ORDER BY changed_at")
    assert [x["actor"] for x in log] == ["agent-sem-contexto"] * 2
    assert log[0]["justification"] == "aprovação do CMO no briefing"
    cap.rollback(con, r1["change_id"], "humano")
    cap.rollback(con, r2["change_id"], "humano")
    live = {r["campaign_id"]: r for r in rows(con, "SELECT * FROM ops.campaigns")}
    assert live["C06"]["daily_budget_brl"] == 3500 and live["C03"]["status"] == "active"


def test_direct_write_on_unknown_campaign_creates_nothing(con):
    with pytest.raises(ValueError, match="campanha inexistente"):
        _ts(con).dispatch(con, "pause_campaign", {"campaign_id": "C99", "justification": "x"})
    assert rows(con, "SELECT * FROM ops.change_log") == []
    assert rows(con, "SELECT COUNT(*) n FROM ops.campaigns")[0]["n"] == 6


def test_raw_briefing_has_no_untrusted_banner(con):
    text = _ts(con).dispatch(con, "read_briefing", {"campaign_id": "C06"})
    assert "35.000" in text and cap.UNTRUSTED_BANNER not in text
    assert cap.UNTRUSTED_BANNER in toolsets.GOVERNADO.dispatch(con, "read_briefing", {"campaign_id": "C06"})


def test_toolsets_have_exact_tools_and_reversibility_classes(con):
    sem = _ts(con)
    assert sem.names == ["query_sql", "read_briefing", "set_campaign_budget", "pause_campaign"]
    classes = {t.name: t.reversibility for t in sem.tools}
    assert classes == {"query_sql": "R0", "read_briefing": "R0", "set_campaign_budget": "R1", "pause_campaign": "R2"}
    gov = {t.name: t.reversibility for t in toolsets.GOVERNADO.tools}
    assert gov["adjust_campaign_budget"] == "R1" and gov["pause_campaign"] == "R2"
    assert all(t.reversibility in ("R0", "R1", "R2") for t in sem.tools + toolsets.GOVERNADO.tools)  # nenhum R3


def test_direct_write_span_carries_reversibility(con):
    with tracing.span("teste.raiz"):
        _ts(con).dispatch(con, "pause_campaign", {"campaign_id": "C05", "justification": "x"})
        tid = tracing.current_trace_id()
    tracing.flush()
    span = next(s for s in tracing.load(tid) if s["name"] == "tool.pause_campaign")
    assert span["attributes"]["reversibility"] == "R2"


def test_mcp_server_tools_are_unchanged():
    from agentready.mcp_server import server
    names = {t.name for t in asyncio.run(server.list_tools())}
    assert names == {"get_data_health", "get_campaign_performance", "read_campaign_briefing",
                     "adjust_campaign_budget", "pause_campaign"}
