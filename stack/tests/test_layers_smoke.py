"""Fumaça: o dbt reconstrói todas as camadas a partir da Bronze (fase Fundacional)."""

TABLES = ["silver.campaigns", "silver.ad_spend", "silver.conversions", "quarantine.conversions",
          "meta.batch_status", "meta.contract_registry", "gold.dim_campaign", "gold.campaign_daily",
          "gold.source_health"]


def test_all_layers_exist_and_are_not_empty(con):
    for t in TABLES:
        n = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        assert n > 0, f"{t} está vazia"


def test_registry_reads_contract_parameters(con):
    rows = {r[0]: r[1:] for r in con.execute(
        "SELECT contract, max_quarantine_rate, sla_hours, partition_by, len(missing_columns) FROM meta.contract_registry").fetchall()}
    assert rows["conversions"] == (0.05, 24.0, "source", 0)
    assert set(rows) == {"campaigns", "ad_spend", "conversions"}
