-- Pilar VOLUME (Fase 2): mesma regra de observability.volume() — linhas recebidas por fonte no dia de
-- negócio de ontem vs mediana dos 14 dias anteriores (dias sem linha fora da mediana), na Bronze.
-- Usa current_date, exatamente como a trilha padrão. Linha de base curta = 'warn' (pesquisa R7).
{%- set lo, hi = obs_band('volume') %}
with d as (
    select s.source, cast(t.day as date) as day, count(c.source) as n
    from (select distinct source from {{ source('bronze', 'conversions') }} where source is not null) s
    cross join range(cast(current_date - 15 as timestamp), cast(current_date as timestamp), interval 1 day) t(day)
    left join {{ source('bronze', 'conversions') }} c
           on c.source = s.source and try_cast(c.converted_at as date) = cast(t.day as date)
    group by all
),
agg as (
    select source,
           max(n) filter (where day = current_date - 1)                        as n,
           median(n) filter (where day < current_date - 1 and n > 0)           as baseline,
           count(*) filter (where day < current_date - 1 and n > 0)            as history_points
    from d group by source
)
select 'volume'                                                            as pillar,
       'conversions/' || source                                            as target,
       case when history_points < {{ obs_min_history() }} then 'warn'
            when (case when baseline > 0 then n / baseline else 1 end) between {{ lo }} and {{ hi }} then 'pass'
            else 'fail' end                                                as status,
       cast(n as double)                                                   as observed,
       baseline,
       case when baseline > 0 then n / baseline else 1 end                 as ratio,
       case when history_points < {{ obs_min_history() }}
            then 'histórico insuficiente (' || history_points || ' de ' || {{ obs_min_history() }}
                 || ' dias necessários); ontem: ' || n || ' linhas recebidas'
            else 'ontem: ' || n || ' linhas recebidas vs mediana ' || format('{:.0f}', baseline)
                 || ' (' || format('{:.1f}', case when baseline > 0 then n / baseline else 1 end) || 'x)'
       end                                                                 as detail
from agg
