-- Pilar DISTRIBUIÇÃO (Fase 2): mesma regra de observability.distribution() — ticket médio do ÚLTIMO
-- lote de cada fonte vs mediana dos lotes da fonte, sobre a Silver JÁ depois do disjuntor (com o
-- disjuntor ligado, o lote anômalo saiu da Silver e o pilar volta a passar, como na trilha padrão).
{%- set lo, hi = obs_band('distribution') %}
with b as (
    select source, batch_id, max(ingested_at) as ing, avg(order_value_brl) as avg_ticket
    from {{ ref('conversions') }} group by all
),
base as (
    select source, median(avg_ticket) as med, count(*) as history_points from b group by source
),
latest as (
    select b.*, base.med, base.history_points, b.avg_ticket / base.med as ratio
    from b join base using (source)
    qualify row_number() over (partition by source order by ing desc) = 1
)
select 'distribuição'                                                       as pillar,
       'conversions/' || source || '.order_value_brl'                       as target,
       case when history_points < {{ obs_min_history() }} then 'warn'
            when ratio between {{ lo }} and {{ hi }} then 'pass'
            else 'fail' end                                                 as status,
       avg_ticket                                                           as observed,
       med                                                                  as baseline,
       ratio,
       case when history_points < {{ obs_min_history() }}
            then 'histórico insuficiente (' || history_points || ' de ' || {{ obs_min_history() }}
                 || ' lotes necessários); ticket médio do último lote ' || batch_id || ': R$ '
                 || format('{:,.2f}', avg_ticket)
            else 'ticket médio do último lote ' || batch_id || ': R$ ' || format('{:,.2f}', avg_ticket)
                 || ' vs mediana R$ ' || format('{:,.2f}', med) || ' (' || format('{:.1f}', ratio) || 'x)'
       end                                                                  as detail
from latest
