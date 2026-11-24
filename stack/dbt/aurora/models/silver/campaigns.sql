-- silver.campaigns: só linhas válidas de lotes aprovados, com os tipos do contrato.
-- Em quebra de esquema mantém o último estado bom (pesquisa R6).
with new_rows as (
    select {{ contract_param('campaigns', 'silver_select') }}, k.batch_id
    from {{ ref('contract_checked__campaigns') }} k
    join {{ ref('batch_quarantine_rate') }} b on b.contract = 'campaigns' and b.batch_id = k.batch_id
    where len(k.violations) = 0 and b.rate <= b.max_rate
)
select * from new_rows where not {{ schema_broken('campaigns') }}
{{ keep_previous_if_broken('campaigns') }}
