"""Estágio de contrato no dbt (US3, Bloco 1): quarentena por linha, disjuntor por lote,
quebra de esquema mantém o último estado bom (FR-010, FR-011, FR-012, SC-005)."""
from datetime import timedelta

from agentready.db import connect, rows

from conftest import REF


def _q(sql, params=None):
    c = connect()
    try:
        return rows(c, sql, params)
    finally:
        c.close()


def test_quarantines_rows_with_reasons(built):
    reasons = {r["v"] for r in _q("SELECT DISTINCT split_part(unnest(violations), ':', 1) v FROM quarantine.conversions")}
    assert {"duplicado", "order_value_brl", "campaign_id", "lote barrado pelo disjuntor"} <= reasons
    details = " ".join(r["v"] for r in _q("SELECT DISTINCT unnest(violations) v FROM quarantine.conversions"))
    assert "abaixo do mínimo 0" in details and "tipo inválido" in details and "fora do domínio C99" in details
    # nenhuma linha em quarentena chegou à Silver
    leaked = _q("""SELECT COUNT(*) n FROM silver.conversions s JOIN quarantine.conversions q
                   ON s.conversion_id = json_extract_string(q.payload, '$.conversion_id') AND s.batch_id = q.batch_id""")
    assert leaked[0]["n"] == 0
    assert _q("SELECT COUNT(*) - COUNT(DISTINCT conversion_id) n FROM silver.conversions")[0]["n"] == 0


def test_bars_batch_over_limit(built):
    broken_batch = f"ga4-{(REF.date() - timedelta(days=20)).isoformat()}"
    st = _q("SELECT status, rate FROM meta.batch_status WHERE batch_id = ?", [broken_batch])
    assert st and st[0]["status"] == "barred" and st[0]["rate"] > 0.05
    assert _q("SELECT COUNT(*) n FROM silver.conversions WHERE batch_id = ?", [broken_batch])[0]["n"] == 0
    # as linhas válidas do lote barrado também foram para a quarentena, com o motivo do disjuntor
    assert _q("""SELECT COUNT(*) n FROM quarantine.conversions WHERE batch_id = ?
                 AND violations[1] LIKE 'lote barrado pelo disjuntor%'""", [broken_batch])[0]["n"] > 0


def test_duplicate_retry_batch_quarantined(built):
    retry = _q("SELECT batch_id, status, rate FROM meta.batch_status WHERE batch_id LIKE '%-retry'")
    assert retry and retry[0]["status"] == "barred" and retry[0]["rate"] == 1.0
    assert _q("SELECT COUNT(*) n FROM silver.conversions WHERE batch_id LIKE '%-retry'")[0]["n"] == 0
    dup = _q("""SELECT COUNT(*) n FROM quarantine.conversions WHERE batch_id LIKE '%-retry'
                AND violations[1] LIKE 'duplicado%'""")
    assert dup[0]["n"] > 0


def test_schema_break_keeps_last_good(built, dbt):
    before = _q("SELECT COUNT(*) n, SUM(order_value_brl) s FROM silver.conversions")[0]
    q_before = _q("SELECT COUNT(*) n FROM quarantine.conversions")[0]["n"]
    c = connect()
    c.execute("ALTER TABLE bronze.conversions DROP COLUMN campaign_id")       # deploy upstream quebrou o esquema
    c.close()
    dbt()                                                                     # nada falha: Gold continua sendo construída
    after = _q("SELECT COUNT(*) n, SUM(order_value_brl) s FROM silver.conversions")[0]
    assert after == before, "a Silver tem de manter o último estado bom"
    assert _q("SELECT COUNT(*) n FROM quarantine.conversions")[0]["n"] == q_before
    st = _q("SELECT DISTINCT status, rate FROM meta.batch_status WHERE contract='conversions'")
    assert st == [{"status": "barred", "rate": 1.0}]
    reg = _q("SELECT missing_columns FROM meta.contract_registry WHERE contract='conversions'")[0]
    assert reg["missing_columns"] == ["campaign_id"]


def test_quality_alert_only_for_new_problems(built, dbt):
    """Pesquisa R7: o lote antigo barrado é permanente; o alerta só dispara para problema NOVO."""
    import pytest
    from agentready import incidents
    from agentready_stack import tasks

    with pytest.raises(tasks.QualityAlert):           # primeira execução: tudo é novo
        tasks.quality_alert()
    tasks.close_run("execucao-1")                      # marca d'água = última carga boa
    assert tasks.quality_alert()["new_barred"] == []   # mesmos lotes de antes: verde
    c = connect()
    incidents.inject(c, "lote_duplicado")              # upstream reenviou o lote de ontem
    c.close()
    dbt()
    with pytest.raises(tasks.QualityAlert) as e:
        tasks.quality_alert()
    assert "redelivery" in str(e.value)
