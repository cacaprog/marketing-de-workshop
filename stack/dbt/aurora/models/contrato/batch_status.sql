-- meta.batch_status: o "placar" por lote que humanos e o agente (get_data_health) consultam.
-- Fase 2: barred_by diz QUEM barrou — 'contrato' (taxa de quarentena acima do limite) ou
-- 'distribuicao' (disjuntor de distribuição ligado e ticket médio fora da faixa). O contrato vence.
with dist as (
    select batch_id, bool_or(out_of_band) as out_of_band
    from {{ ref('distribution_by_batch') }}
    group by batch_id
),
scored as (
    select b.contract,
           r.contract_version,
           b.batch_id,
           b.batch_ingested_at                                  as ingested_at,
           b.n                                                  as "rows",
           b.bad                                                as quarantined,
           b.rate,
           case when b.rate > b.max_rate then 'contrato'
                when {{ breaker_on() }} and b.contract = 'conversions' and coalesce(d.out_of_band, false)
                     then 'distribuicao'
           end                                                  as barred_by
    from {{ ref('batch_quarantine_rate') }} b
    join {{ ref('contract_registry') }} r using (contract)
    left join dist d on d.batch_id = b.batch_id
)
select contract, contract_version, batch_id, ingested_at, "rows", quarantined, rate,
       case when barred_by is not null then 'barred' else 'passed' end as status,
       barred_by
from scored
