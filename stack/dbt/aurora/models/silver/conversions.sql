-- silver.conversions: só linhas válidas de lotes aprovados, com os tipos do contrato.
-- Em quebra de esquema mantém o último estado bom (pesquisa R6).
-- Fase 2: lotes barrados pelo disjuntor de distribuição também ficam de fora (pesquisa R3).
with new_rows as (
    select {{ contract_param('conversions', 'silver_select') }}, k.batch_id
    from {{ ref('contract_checked__conversions') }} k
    join (select batch_id, status, barred_by from {{ ref('batch_status') }} where contract = 'conversions') s
         on s.batch_id = k.batch_id
    where len(k.violations) = 0 and s.status = 'passed'
)
select * from new_rows where not {{ schema_broken('conversions') }}
{{ keep_previous_if_broken('conversions') }}
