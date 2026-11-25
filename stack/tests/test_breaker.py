"""Disjuntor de distribuição no estágio de contrato (Fase 2, FR-005/FR-008, pesquisa R3).

Ligado: o lote cujo ticket médio sai da faixa vai para a quarentena com o motivo da trilha padrão,
fica barrado (barred_by='distribuicao') e não chega à Silver, à Gold nem ao agente.
Desligado: só o relatório de observabilidade acusa (o contrato continua aprovando o lote).
"""
from agentready.db import connect, rows

REASON = "anomalia de distribuição: ticket médio fora da banda"


def _q(sql, params=None):
    c = connect()
    try:
        return rows(c, sql, params or [])
    finally:
        c.close()


def _redelivery():
    r = _q("SELECT batch_id FROM bronze.conversions WHERE batch_id LIKE '%-redelivery' LIMIT 1")
    assert r, "o incidente deveria ter criado um lote -redelivery"
    return r[0]["batch_id"]


def test_on_quarantines_and_bars(run_incident):
    r = run_incident("centavos", breaker=True)
    assert r.returncode == 0, r.stdout[-3000:]   # os testes de veredito ficam fora do build padrão (selectors.yml)
    batch = _redelivery()
    st = _q("SELECT status, barred_by FROM meta.batch_status WHERE batch_id = ?", [batch])
    assert st == [{"status": "barred", "barred_by": "distribuicao"}]
    q = _q("SELECT COUNT(*) AS n, bool_and(list_contains(violations, ?)) AS all_reason "
           "FROM quarantine.conversions WHERE batch_id = ?", [REASON, batch])[0]
    assert q["n"] > 0 and q["all_reason"], q
    assert _q("SELECT COUNT(*) AS n FROM silver.conversions WHERE batch_id = ?", [batch])[0]["n"] == 0
    # Gold: a receita de ontem não pode carregar valores 100x (nenhuma linha do lote chega à Gold)
    gold = _q("SELECT max(gross_revenue_brl / nullif(orders, 0)) AS t FROM gold.campaign_daily")[0]["t"]
    assert gold < 2000, f"ticket médio na Gold {gold}: o lote em centavos vazou"


def test_off_reports_only(run_incident):
    run_incident("centavos", breaker=False)
    batch = _redelivery()
    st = _q("SELECT status, barred_by FROM meta.batch_status WHERE batch_id = ?", [batch])
    assert st == [{"status": "passed", "barred_by": None}]
    assert _q("SELECT COUNT(*) AS n FROM silver.conversions WHERE batch_id = ?", [batch])[0]["n"] > 0


def test_contract_barred_not_requarantined(run_incident):
    """renomeacao: o contrato barra o lote (esquema). O disjuntor não o quarentena de novo."""
    run_incident("renomeacao", breaker=True)
    batch = _redelivery()
    st = _q("SELECT barred_by FROM meta.batch_status WHERE batch_id = ?", [batch])
    assert st == [{"barred_by": "contrato"}]
    n = _q("SELECT COUNT(*) AS n FROM quarantine.conversions WHERE list_contains(violations, ?)", [REASON])[0]["n"]
    assert n == 0


def test_short_history_never_blocks(short_history, dbt):
    dbt(vars_={"block_on_distribution_anomaly": "true"}, expect_ok=False)
    assert _q("SELECT COUNT(*) AS n FROM meta.batch_status WHERE barred_by = 'distribuicao'")[0]["n"] == 0


def test_breaker_model_error_stops_gold(built, dbt):
    """FR-008(a): se a entrada do disjuntor não pode ser calculada, Silver e Gold não são reconstruídas."""
    before = _q("SELECT COUNT(*) AS n, sum(spend_brl) AS s FROM gold.campaign_daily")[0]
    c = connect()
    c.execute("UPDATE gold.campaign_daily SET spend_brl = spend_brl + 1")   # marca: um rebuild apagaria isto
    c.close()
    r = dbt(vars_={"obs_force_error": "true"}, expect_ok=False)
    assert r.returncode != 0
    assert "distribution_by_batch" in r.stdout
    after = _q("SELECT COUNT(*) AS n, sum(spend_brl) AS s FROM gold.campaign_daily")[0]
    assert after["n"] == before["n"] and round(after["s"] - before["s"]) == before["n"], \
        "a Gold foi reconstruída mesmo com o disjuntor sem entrada"


def test_override_is_per_run(built):
    from agentready_stack import tasks
    tasks.ingest({"disjuntor_distribuicao": "ligado"}, "run-1")
    tasks.ingest({}, "run-2")
    got = _q("SELECT dag_run_id, block_on_distribution_anomaly AS v, source FROM ops.stack_run_settings "
             "ORDER BY decided_at")
    assert got[-2] == {"dag_run_id": "run-1", "v": True, "source": "override"}
    assert got[-1]["dag_run_id"] == "run-2" and got[-1]["source"] == "compartilhado"
    assert got[-1]["v"] is False, "config/guardrails.yaml deixa o disjuntor desligado por padrão"
