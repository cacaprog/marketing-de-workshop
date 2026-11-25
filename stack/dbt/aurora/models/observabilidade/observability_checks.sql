-- meta.observability_checks (Fase 2): os 4 pilares de dados desta execução, um veredito por pilar e alvo
-- (contracts/observability-check.schema.json). Reconstruída a cada execução; o histórico fica no
-- Elementary (resultado de cada teste de veredito por execução). Substitui observability.report().
{{ config(alias='observability_checks') }}
select pillar, target, status, observed, baseline, ratio, detail,
       cast({{ "'" ~ var('reference_ts') ~ "'" if var('reference_ts') else 'now()' }} as timestamp) as reference_ts
from (
    select * from {{ ref('obs_frescor') }}
    union all by name
    select * from {{ ref('obs_volume') }}
    union all by name
    select * from {{ ref('obs_distribuicao') }}
    union all by name
    select * from {{ ref('obs_esquema') }}
)
