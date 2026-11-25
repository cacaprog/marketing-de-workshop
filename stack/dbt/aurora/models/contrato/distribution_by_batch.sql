-- meta.distribution_by_batch (Fase 2): a ENTRADA do disjuntor de distribuição (pesquisa R3).
-- Mesma regra de observability.distribution_by_batch() da trilha padrão, calculada ANTES do disjuntor,
-- sobre as linhas que passaram no contrato, de lotes que o contrato NÃO barrou (um lote barrado pelo
-- contrato nunca é barrado de novo). Baseline = mediana do ticket médio de todos os lotes da fonte
-- (o próprio lote incluído, como na trilha padrão).
{%- set lo, hi = obs_band('distribution') %}
{%- if obs_force_error() %}
select * from obs_force_error_relacao_inexistente   -- só para o teste FR-008(a)
{%- else %}
with ok_rows as (
    select k.source,
           k.batch_id,
           k.ingested_at,
           try_cast(k.order_value_brl as double) as order_value_brl
    from {{ ref('contract_checked__conversions') }} k
    join {{ ref('batch_quarantine_rate') }} b on b.contract = 'conversions' and b.batch_id = k.batch_id
    where len(k.violations) = 0 and b.rate <= b.max_rate and not {{ schema_broken('conversions') }}
),
b as (
    select source, batch_id, max(ingested_at) as ingested_at, avg(order_value_brl) as avg_ticket
    from ok_rows group by all
),
base as (
    select source, median(avg_ticket) as baseline, count(*) as history_points from b group by source
)
select b.source,
       b.batch_id,
       b.ingested_at,
       b.avg_ticket,
       base.baseline,
       b.avg_ticket / base.baseline                                         as ratio,
       cast(base.history_points as integer)                                 as history_points,
       (b.avg_ticket / base.baseline not between {{ lo }} and {{ hi }})
         and base.history_points >= {{ obs_min_history() }}                 as out_of_band
from b join base using (source)
{%- endif %}
