-- Pilar FRESCOR (Fase 2): mesma regra de observability.freshness() — um veredito por linha de
-- gold.source_health (frescor por feed/partição, SLA do contrato). Detalhe com o texto da trilha padrão.
select 'frescor'                                                   as pillar,
       dataset || '/' || "partition"                               as target,
       case when status = 'fresh' then 'pass' else 'fail' end      as status,
       age_hours                                                   as observed,
       sla_hours                                                   as baseline,
       cast(null as double)                                        as ratio,
       'última carga ok há ' || coalesce(cast(age_hours as varchar), 'None') || 'h (SLA '
         || format('{:.0f}', sla_hours) || 'h)'                    as detail
from {{ ref('source_health') }}
