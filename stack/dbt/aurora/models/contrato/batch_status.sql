-- meta.batch_status: o "placar" por lote que humanos e o agente (get_data_health) consultam.
select b.contract,
       r.contract_version,
       b.batch_id,
       b.batch_ingested_at                                  as ingested_at,
       b.n                                                  as "rows",
       b.bad                                                as quarantined,
       b.rate,
       case when b.rate > b.max_rate then 'barred' else 'passed' end as status
from {{ ref('batch_quarantine_rate') }} b
join {{ ref('contract_registry') }} r using (contract)
