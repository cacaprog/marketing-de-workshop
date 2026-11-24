-- silver.ad_spend: só linhas válidas de lotes aprovados, com os tipos do contrato.
-- Em quebra de esquema mantém o último estado bom (pesquisa R6).
with new_rows as (
    select {{ contract_param('ad_spend', 'silver_select') }}, k.batch_id
    from {{ ref('contract_checked__ad_spend') }} k
    join {{ ref('batch_quarantine_rate') }} b on b.contract = 'ad_spend' and b.batch_id = k.batch_id
    where len(k.violations) = 0 and b.rate <= b.max_rate
)
select * from new_rows where not {{ schema_broken('ad_spend') }}
{{ keep_previous_if_broken('ad_spend') }}
