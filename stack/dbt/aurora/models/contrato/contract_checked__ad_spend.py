"""Bronze ad_spend + violações do contrato ODCS (regras de agentready.contracts.violation_exprs)."""
from agentready_stack.dbt_contracts import checked_relation


def model(dbt, session):
    dbt.config(materialized="table")
    dbt.source("bronze", "ad_spend")
    dbt.ref("contract_registry")
    return checked_relation(session, "ad_spend")
