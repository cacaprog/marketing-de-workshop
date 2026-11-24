"""Pipeline Medalhão: Bronze -> (contratos) -> Silver -> Gold + saúde dos dados.

Humanos investigam Bronze/Silver/Quarentena. O agente só enxerga a Gold, e a Gold
carrega junto o estado de frescor de cada fonte (gold.source_health).
"""
from __future__ import annotations

from datetime import datetime

from agentready import contracts
from agentready.db import connect, rows
from agentready.settings import guardrails


def freshness(con, now: datetime | None = None) -> list[dict]:
    """SLA de frescor = idade da ÚLTIMA CARGA BEM-SUCEDIDA (ingested_at na Silver), não do evento."""
    now = now or datetime.now()
    out = []
    for c in contracts.load_all():
        if c.freshness_hours is None:
            continue
        part = c.freshness_partition
        sel = f"{part} AS partition" if part else "'*' AS partition"
        grp = f"GROUP BY {part}" if part else ""
        for r in rows(con, f"SELECT {sel}, max(ingested_at) AS last_ok FROM silver.{c.table} {grp}"):
            age = (now - r["last_ok"]).total_seconds() / 3600 if r["last_ok"] else float("inf")
            out.append({"dataset": c.table, "partition": r["partition"], "last_success_ingest": r["last_ok"],
                        "age_hours": round(age, 1), "sla_hours": c.freshness_hours,
                        "status": "fresh" if age <= c.freshness_hours else "stale"})
    return out


def build_gold(con) -> None:
    con.execute("""
        CREATE OR REPLACE TABLE gold.dim_campaign AS
        SELECT campaign_id, campaign_name, channel, objective, owner,
               CASE WHEN channel = 'meta' THEN 'meta_capi' ELSE 'ga4' END AS conversion_source
        FROM silver.campaigns""")
    # Grão campanha x dia. Conversões são PRÉ-AGREGADAS antes do join: evita fan-out.
    con.execute("""
        CREATE OR REPLACE TABLE gold.campaign_daily AS
        WITH conv AS (
            SELECT campaign_id, CAST(converted_at AS DATE) AS day, COUNT(*) AS orders,
                   SUM(order_value_brl) AS gross_revenue_brl, SUM(discount_brl) AS discount_brl
            FROM silver.conversions GROUP BY ALL)
        SELECT s.spend_date AS day, s.campaign_id, d.campaign_name, d.channel, d.objective, d.conversion_source,
               s.impressions, s.clicks, s.spend_brl,
               COALESCE(c.orders, 0) AS orders,
               COALESCE(c.gross_revenue_brl, 0) AS gross_revenue_brl,
               COALESCE(c.discount_brl, 0) AS discount_brl
        FROM silver.ad_spend s
        JOIN gold.dim_campaign d USING (campaign_id)
        LEFT JOIN conv c ON c.campaign_id = s.campaign_id AND c.day = s.spend_date""")


def write_health(con, now: datetime | None = None) -> list[dict]:
    """Publica gold.source_health — o 'painel de luzes' que o agente consulta antes de agir."""
    fr = freshness(con, now)
    con.execute("""CREATE OR REPLACE TABLE gold.source_health (dataset VARCHAR, partition VARCHAR,
        last_success_ingest TIMESTAMP, age_hours DOUBLE, sla_hours DOUBLE, status VARCHAR)""")
    con.executemany("INSERT INTO gold.source_health VALUES (?,?,?,?,?,?)",
                    [(f["dataset"], f["partition"], f["last_success_ingest"], f["age_hours"], f["sla_hours"],
                      f["status"]) for f in fr])
    return fr


def run(now: datetime | None = None) -> dict:
    con = connect()
    results = [contracts.apply(con, c) for c in contracts.load_all()]
    blocked = []
    if guardrails()["observability"]["block_on_distribution_anomaly"]:
        from agentready import observability
        blocked = observability.block_anomalous_batches(con)
    build_gold(con)
    health = write_health(con, now)
    con.close()
    return {"contracts": results, "health": health, "blocked_by_observability": blocked}
