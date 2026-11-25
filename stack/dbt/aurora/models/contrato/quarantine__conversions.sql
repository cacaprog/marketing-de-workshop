-- quarantine.conversions: linhas que violam o contrato + linhas de lotes barrados pelo disjuntor do
-- contrato + (Fase 2) linhas de lotes barrados pelo disjuntor de DISTRIBUIÇÃO, com o mesmo motivo da
-- trilha padrão (observability.block_anomalous_batches).
{{ config(schema='quarantine', alias='conversions') }}
with new_rows as (
    select {{ contract_param('conversions', 'quarantine_payload') }} as payload,
           k.batch_id,
           k.ingested_at,
           case when b.rate > b.max_rate and len(k.violations) = 0
                then ['lote barrado pelo disjuntor: ' || round(b.rate * 100, 1) || '% de quarentena > '
                      || cast(round(b.max_rate * 100) as integer) || '%']
                when s.barred_by = 'distribuicao'
                then ['anomalia de distribuição: ticket médio fora da banda']
                else k.violations end                       as violations,
           now()                                            as quarantined_at
    from {{ ref('contract_checked__conversions') }} k
    join {{ ref('batch_quarantine_rate') }} b on b.contract = 'conversions' and b.batch_id = k.batch_id
    join (select batch_id, status, barred_by from {{ ref('batch_status') }} where contract = 'conversions') s
         on s.batch_id = k.batch_id
    where len(k.violations) > 0 or b.rate > b.max_rate or s.barred_by = 'distribuicao'
)
select * from new_rows where not {{ schema_broken('conversions') }}
{{ keep_previous_if_broken('conversions') }}
