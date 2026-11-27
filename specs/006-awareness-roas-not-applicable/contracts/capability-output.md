# Contract: `get_campaign_performance` output (capability and MCP tool)

One object per campaign. Today's fields are unchanged; new fields in **bold**.

```json
{"campaign_id": "C05", "campaign_name": "TikTok - Awareness", "objective": "awareness",
 "spend": 33710.21, "net_revenue": 19725.87, "orders": 138,
 "roas": null, "roas_status": "nao_se_aplica",
 "cac": null,  "cac_status": "nao_se_aplica",
 "nao_se_aplica": {"roas": "campanhas de awareness são avaliadas por alcance e frequência, não por eficiência de conversão",
                   "cac":  "campanhas de awareness são avaliadas por alcance e frequência, não por eficiência de conversão"},
 "data_status": "fresh", "conversions_age_hours": 3.0,
 "daily_budget_brl": 2500.0, "status": "active"}
```

- **`roas_status` / `cac_status`** are present on every row. **`nao_se_aplica`** is present only when at least one metric doesn't apply.
- The tool description gains one sentence: "Métrica com status `nao_se_aplica` não se aplica à campanha (veja o motivo); não é dado desconhecido."
- Stale campaigns (C03, C04): `roas: null, roas_status: "desconhecido"`, as today plus the status.

## Display (Blocks 1 and 2, `agentready ask`)

`semantic.display(rows)` replaces each `nao_se_aplica` value with the text **não se aplica**, which `ui.table` renders in its own colour, distinct from the magenta `NULL` that means "desconhecido". The `*_status` and `*_motivo` columns are hidden from those tables; the reason is printed once as a note under them.
