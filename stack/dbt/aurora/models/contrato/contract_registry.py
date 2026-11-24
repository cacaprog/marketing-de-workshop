"""Registro dos contratos ODCS (meta.contract_registry): a ÚNICA fonte de parâmetros de contrato
para os modelos SQL (limite de quarentena, SLA, partição de frescor, colunas ausentes, casts).
Construído a cada execução a partir de contracts/*.odcs.yaml (nada é copiado para o dbt)."""
from agentready_stack.dbt_contracts import registry_relation


def model(dbt, session):
    dbt.config(materialized="table")
    # Dependências explícitas (o dbt só enxerga refs/sources com nomes literais):
    dbt.source("bronze", "campaigns")
    dbt.source("bronze", "ad_spend")
    dbt.source("bronze", "conversions")
    return registry_relation(session)
