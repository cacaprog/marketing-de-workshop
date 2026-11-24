-- gold.campaign_daily: grão campanha x dia. Conversões são PRÉ-AGREGADAS antes do join (sem fan-out).
-- Mesma semântica de pipeline.build_gold(); o "desconhecido" chega ao agente via source_health
-- + camada semântica (NULL), não por esta tabela.
with conv as (
    select campaign_id, cast(converted_at as date) as day, count(*) as orders,
           sum(order_value_brl) as gross_revenue_brl, sum(discount_brl) as discount_brl
    from {{ ref('conversions') }} group by all
)
select s.spend_date as day, s.campaign_id, d.campaign_name, d.channel, d.objective, d.conversion_source,
       s.impressions, s.clicks, s.spend_brl,
       coalesce(c.orders, 0)            as orders,
       coalesce(c.gross_revenue_brl, 0) as gross_revenue_brl,
       coalesce(c.discount_brl, 0)      as discount_brl
from {{ ref('ad_spend') }} s
join {{ ref('dim_campaign') }} d using (campaign_id)
left join conv c on c.campaign_id = s.campaign_id and c.day = s.spend_date
