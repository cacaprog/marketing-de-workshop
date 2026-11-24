"""gold.source_health: frescor por feed/partição — o "painel de luzes" que o agente consulta.

A regra é a função compartilhada agentready.pipeline.freshness() (mesma da trilha padrão,
para a paridade ser exata). O dbt cuida da materialização e da ordem (depois da Silver).
reference_ts vem de models/gold/_gold.yml (modelos Python não chamam var()).
"""
from datetime import datetime

from agentready import pipeline
from agentready_stack.dbt_contracts import values_relation


def model(dbt, session):
    dbt.config(materialized="table")
    dbt.ref("campaigns")
    dbt.ref("ad_spend")
    dbt.ref("conversions")
    ref = dbt.config.get("reference_ts")
    now = datetime.fromisoformat(str(ref)) if ref not in (None, "", "None") else datetime.now()
    rows = pipeline.freshness(session, now)
    return values_relation(session, rows, {
        "dataset": "VARCHAR", "partition": "VARCHAR", "last_success_ingest": "TIMESTAMP",
        "age_hours": "DOUBLE", "sla_hours": "DOUBLE", "status": "VARCHAR"})
