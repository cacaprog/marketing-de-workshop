-- gold.dim_campaign: mesma semântica de pipeline.build_gold().
select campaign_id, campaign_name, channel, objective, owner,
       case when channel = 'meta' then 'meta_capi' else 'ga4' end as conversion_source
from {{ ref('campaigns') }}
