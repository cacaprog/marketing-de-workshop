-- Taxa de quarentena por lote e limite do contrato (disjuntor). Limite vem do contrato, via registro.
with checked as (
    select 'campaigns' as contract, batch_id, ingested_at, violations from {{ ref('contract_checked__campaigns') }}
    union all
    select 'ad_spend', batch_id, ingested_at, violations from {{ ref('contract_checked__ad_spend') }}
    union all
    select 'conversions', batch_id, ingested_at, violations from {{ ref('contract_checked__conversions') }}
)
select k.contract,
       k.batch_id,
       max(k.ingested_at)                                   as batch_ingested_at,
       count(*)                                             as n,
       count(*) filter (where len(k.violations) > 0)        as bad,
       bad / n                                              as rate,
       any_value(r.max_quarantine_rate)                     as max_rate
from checked k
join {{ ref('contract_registry') }} r using (contract)
group by k.contract, k.batch_id
