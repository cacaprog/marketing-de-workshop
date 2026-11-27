"""Promessas da 006: a regra de awareness mora no dado. ROAS e CAC de campanha de awareness = "não se aplica",
distinto de NULL/desconhecido; nada mais muda."""
import asyncio
import copy

import pytest

from agentready import capabilities as cap
from agentready import semantic
from agentready.db import rows

REASON = "campanhas de awareness são avaliadas por alcance e frequência, não por eficiência de conversão"


def _by_campaign(con, metrics=("spend", "net_revenue", "orders", "roas", "cac"), window=14):
    return {r["campaign_id"]: r for r in semantic.query(con, semantic.MetricRequest(list(metrics), ["campaign"], window))[1]}


# ---------- US1: grão de campanha (T005)
def test_awareness_conversion_metrics_do_not_apply(con):
    r = _by_campaign(con)
    c05 = r["C05"]
    for m in ("roas", "cac"):
        assert c05[m] is None and c05[f"{m}_status"] == "nao_se_aplica" and c05[f"{m}_motivo"] == REASON
    for cid in ("C03", "C04"):
        assert r[cid]["roas"] is None and r[cid]["roas_status"] == "desconhecido" and r[cid]["cac_status"] == "desconhecido"
    expected = {"C01": (7.44, 25.35), "C02": (2.78, 62.70), "C06": (0.83, 217.55)}
    for cid, (roas, cac) in expected.items():
        assert r[cid]["roas_status"] == "ok" and r[cid]["cac_status"] == "ok"
        assert r[cid]["roas"] == pytest.approx(roas, abs=0.01) and r[cid]["cac"] == pytest.approx(cac, abs=0.01)
    for m in ("spend", "net_revenue", "orders"):
        assert isinstance(c05[m], (int, float)) and c05[m] > 0


def test_metrics_without_a_rule_keep_their_shape(con):
    r = semantic.query(con, semantic.MetricRequest(["spend", "net_revenue", "orders", "ctr"], ["campaign"], 14))[1]
    assert not any((k.endswith("_status") and k != "data_status") or k.endswith("_motivo") for k in r[0])
    assert all(isinstance(x["ctr"], float) for x in r)


# ---------- US1: agrupamentos (T006)
def test_grouped_results(con):
    by_obj = {r["objective"]: r for r in semantic.query(con, semantic.MetricRequest(["roas", "cac"], ["objective"], 14))[1]}
    assert by_obj["awareness"]["roas_status"] == "nao_se_aplica" and by_obj["awareness"]["cac_status"] == "nao_se_aplica"
    assert by_obj["conversion"]["roas_status"] in ("ok", "desconhecido")
    by_ch = {r["channel"]: r for r in semantic.query(con, semantic.MetricRequest(["roas"], ["channel"], 14))[1]}
    assert by_ch["tiktok"]["roas_status"] == "nao_se_aplica"
    assert by_ch["google_search"]["roas_status"] == "ok" and by_ch["google_search"]["roas_motivo"] is None


def test_total_excludes_awareness_and_says_so(con):
    rows_ = semantic.query(con, semantic.MetricRequest(["roas", "spend"], [], 14))[1]
    t = rows_[0]
    assert t["roas_motivo"] == "exclui 1 campanha(s) de awareness"
    if t["roas_status"] == "ok":   # o total fica desconhecido se alguma fonte estiver atrasada
        manual = rows(con, """SELECT (SUM(gross_revenue_brl) - SUM(discount_brl)) / SUM(spend_brl) r
                              FROM gold.campaign_daily WHERE day >= current_date - 14 AND day < current_date
                              AND objective <> 'awareness'""")[0]["r"]
        assert t["roas"] == pytest.approx(manual)
    else:
        assert t["roas_status"] == "desconhecido"
    assert t["spend"] == pytest.approx(rows(con, """SELECT SUM(spend_brl) s FROM gold.campaign_daily
                                                     WHERE day >= current_date - 14 AND day < current_date""")[0]["s"])


def test_rule_follows_the_current_objective(con):
    con.execute("UPDATE gold.campaign_daily SET objective = 'awareness' WHERE campaign_id = 'C02'")
    assert _by_campaign(con, ("roas",))["C02"]["roas_status"] == "nao_se_aplica"


# ---------- US1: precedência e validação (T007)
def test_not_applicable_wins_over_stale(con):
    con.execute("UPDATE gold.campaign_daily SET objective = 'awareness' WHERE campaign_id = 'C03'")
    c03 = _by_campaign(con, ("roas", "cac"))["C03"]
    assert c03["roas_status"] == "nao_se_aplica" and c03["cac_status"] == "nao_se_aplica"
    assert c03["data_status"] == "stale"


@pytest.mark.parametrize("patch,needle", [({"when": {"canal_inexistente": ["x"]}}, "canal_inexistente"),
                                          ({"rule": "nao_existe"}, "nao_existe")])
def test_malformed_rule_is_refused(patch, needle):
    m = copy.deepcopy(semantic.model())
    m["semantic_model"]["metrics"]["roas"]["not_applicable"].update(patch)
    with pytest.raises(semantic.SemanticError, match=f"roas.*{needle}"):
        semantic.validate_model(m)


# ---------- US1: capacidade e MCP (T008)
def test_capability_carries_status_and_reason(con):
    perf = {p["campaign_id"]: p for p in cap.get_campaign_performance(con)}
    c05 = perf["C05"]
    assert c05["roas"] is None and c05["roas_status"] == "nao_se_aplica" and c05["cac_status"] == "nao_se_aplica"
    assert c05["nao_se_aplica"] == {"roas": REASON, "cac": REASON}
    assert "roas_motivo" not in c05
    assert perf["C03"]["roas_status"] == "desconhecido" and "nao_se_aplica" not in perf["C03"]
    assert "nao_se_aplica" not in perf["C01"] and isinstance(perf["C01"]["roas"], float)


def test_mcp_tool_returns_the_marker_and_its_description_is_unambiguous(con):
    from agentready.mcp_server import server
    tools = {t.name: t for t in asyncio.run(server.list_tools())}
    desc = tools["get_campaign_performance"].description
    assert "nao_se_aplica" in desc and "Métricas NULL = fonte fora do SLA" not in desc
    out = asyncio.run(server.call_tool("get_campaign_performance", {"window_days": 14}))
    assert "nao_se_aplica" in str(out) and REASON in str(out)


# ---------- US3: decisões iguais (T013)
def test_agent_decisions_are_unchanged(con):
    from agentready.agent import NaiveAgent, ReadyAgent
    rep = ReadyAgent().run(con)
    actions = [s.text.split(" -> ")[0] + " -> " + s.data["result"]["status"] for s in rep.steps if s.kind == "action"]
    assert actions == ["adjust_campaign_budget(C06, 2800.0) -> queued_for_approval",
                       "adjust_campaign_budget(C01, 4400.0) -> executed"]
    refusals = [s.text.split(" · ")[0] for s in rep.steps if s.kind == "refusal"]
    assert refusals == ["C03", "C04"]
    assert any(s.text.startswith("C05 · objetivo 'awareness' não é avaliado por ROAS") for s in rep.steps)


def test_naive_agent_is_unchanged(con):
    from agentready.agent import NaiveAgent
    rep = NaiveAgent().run(con)
    assert [s.text.split(" — ")[0] for s in rep.steps if s.kind == "action"][:3] == ["PAUSEI C03", "PAUSEI C04", "PAUSEI C05"]


# ---------- US2: o que as pessoas veem (T016)
@pytest.fixture
def wide(monkeypatch):
    from rich.console import Console

    from agentready import blocks, ui
    c = Console(width=220, highlight=False)
    monkeypatch.setattr(ui, "console", c)
    monkeypatch.setattr(blocks, "console", c, raising=False)
    monkeypatch.setattr(ui, "PAUSE", False)
    return c


def test_display_shows_nao_se_aplica_not_null(con, wide):
    from agentready import ui
    rs = semantic.query(con, semantic.MetricRequest(["roas"], ["campaign"], 14))[1]
    shown = {r["campaign_id"]: r for r in semantic.display(rs)}
    assert shown["C05"]["roas"] == "não se aplica" and shown["C03"]["roas"] is None
    assert not any(k.endswith("_motivo") or (k.endswith("_status") and k != "data_status") for k in shown["C05"])
    assert semantic.motivos(rs) == [REASON]
    with wide.capture() as cap_:
        ui.table(semantic.display(rs))
    out = cap_.get()
    assert "não se aplica" in out and "NULL" in out


def test_block2_official_cell_says_nao_se_aplica(con, wide):
    from agentready import blocks
    with wide.capture() as cap_:
        blocks.block2()
    out = cap_.get()
    c05 = next(line for line in out.splitlines() if "C05" in line and "│" in line)
    assert "não se aplica" in c05
    cells = [c.strip() for c in c05.split("│") if c.strip()]
    assert len(cells) >= 5 and all(any(ch.isdigit() for ch in c) for c in cells[2:5])   # os palpites são números
    assert "C05 é awareness" in out
