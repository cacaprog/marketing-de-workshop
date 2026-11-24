-- quarantine.conversions: linhas que violam o contrato + linhas de lotes barrados pelo disjuntor.
{{ config(schema='quarantine', alias='conversions') }}
with new_rows as (
    select {{ contract_param('conversions', 'quarantine_payload') }} as payload,
           k.batch_id,
           k.ingested_at,
           case when b.rate > b.max_rate and len(k.violations) = 0
                then ['lote barrado pelo disjuntor: ' || round(b.rate * 100, 1) || '% de quarentena > '
                      || cast(round(b.max_rate * 100) as integer) || '%']
                else k.violations end                       as violations,
           now()                                            as quarantined_at
    from {{ ref('contract_checked__conversions') }} k
    join {{ ref('batch_quarantine_rate') }} b on b.contract = 'conversions' and b.batch_id = k.batch_id
    where len(k.violations) > 0 or b.rate > b.max_rate
)
select * from new_rows where not {{ schema_broken('conversions') }}
{{ keep_previous_if_broken('conversions') }}
