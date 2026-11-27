# Data Model: Conversion Metrics "não se aplica" for Awareness Campaigns

No new tables. The change is in the semantic model (YAML) and in the shape of official metric results.

## Metric applicability rule (semantic model)

Belongs to one metric. Fields ([contracts/semantic-model.md](contracts/semantic-model.md)):

| Field | Type | Rules |
|---|---|---|
| `when` | map of dimension column → list of values | today only `objective: [awareness]`; the column must exist in the semantic table |
| `reason` | string, pt-BR | shown to people and models |
| `rule` | domain-rule id | must exist in `domain_model.rules` |

Declared on: `roas`, `cac`. Not declared on: `spend`, `net_revenue`, `orders`, `ctr`. The compiler refuses to load a `when` column that isn't in the table, or a `rule` id that doesn't exist (pt-BR error naming the metric).

## Metric result cell (three states)

For a metric with an applicability rule, each result row carries:

| Column | Values | Meaning |
|---|---|---|
| `<metric>` | number or NULL | NULL whenever the status isn't `ok` |
| `<metric>_status` | `ok` · `desconhecido` · `nao_se_aplica` | `desconhecido` = stale feed (Principle III); `nao_se_aplica` = the rule applies to every campaign in the group |
| `<metric>_motivo` | text or NULL | the reason when `nao_se_aplica`; "exclui N campanha(s) de awareness" when a mixed group's value leaves some out |

Precedence: `nao_se_aplica` > `desconhecido` > `ok`. `data_status` and `conversions_age_hours` keep their current meaning. Metrics without a rule keep today's columns only.

## Capability row (`get_campaign_performance`)

Today's fields, plus `roas_status`, `cac_status`, and a `nao_se_aplica` map `{metric: reason}` present only on rows where some metric doesn't apply ([contracts/capability-output.md](contracts/capability-output.md)).
