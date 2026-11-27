# Contract: semantic model and compiled results

## YAML (`semantic/marketing.semantic.yaml`, version 1.2.0)

```yaml
domain_model:
  rules:
    - id: awareness_nao_usa_roas          # id unchanged (spec 005 refers to it)
      text: Campanhas com objective = awareness são avaliadas por alcance e frequência, NUNCA por métricas de eficiência de conversão (ROAS, CAC).

semantic_model:
  metrics:
    roas:
      label: ROAS (receita líquida / investimento)
      type: ratio
      numerator: net_revenue
      denominator: spend
      synonyms: [...]
      not_applicable:
        when: {objective: [awareness]}
        reason: campanhas de awareness são avaliadas por alcance e frequência, não por eficiência de conversão
        rule: awareness_nao_usa_roas
    cac:
      ...                                  # same not_applicable block
```

## Compiled SQL (shape, for a metric `m` with a rule; `cond` = `t.objective IN ('awareness')`)

- each measure inside `m`: `SUM(expr) FILTER (WHERE NOT (cond))`;
- extra columns in the inner query: `COUNT(*) FILTER (WHERE NOT (cond)) AS _m_ok`, `COUNT(DISTINCT t.campaign_id) FILTER (WHERE cond) AS _m_excl`;
- outer select:
  - `m`: `CASE WHEN _m_ok = 0 THEN NULL WHEN _stale THEN NULL ELSE m END` (the stale arm only if `m` depends on conversions, as today);
  - `m_status`: `CASE WHEN _m_ok = 0 THEN 'nao_se_aplica' WHEN _stale THEN 'desconhecido' ELSE 'ok' END`;
  - `m_motivo`: `CASE WHEN _m_ok = 0 THEN '<reason>' WHEN _m_excl > 0 THEN 'exclui ' || _m_excl || ' campanha(s) de awareness' END`.

The SQL is still a pure function of the request, so different phrasings of the same request keep compiling to identical SQL.

## Expected results (morning scenario, 14 days, by campaign)

| campaign | roas | roas_status | cac | cac_status |
|---|---|---|---|---|
| C01 | 7,44 | ok | 25,35 | ok |
| C02 | 2,78 | ok | 62,70 | ok |
| C03 | NULL | desconhecido | NULL | desconhecido |
| C04 | NULL | desconhecido | NULL | desconhecido |
| C05 | NULL | nao_se_aplica (+ motivo) | NULL | nao_se_aplica (+ motivo) |
| C06 | 0,83 | ok | 217,55 | ok |

The C01, C02 and C06 values are the same as before the change (measured 2026-11-27).
