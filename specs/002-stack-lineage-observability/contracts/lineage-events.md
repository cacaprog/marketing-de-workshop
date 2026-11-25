# Interface: lineage events (OpenLineage → Marquez)

| Property | Value |
|---|---|
| Transport | HTTP, `http://marquez-api:5000/api/v1/lineage`, timeout 5 s |
| Job namespace | `aurora` |
| Dataset namespace | `duckdb:///opt/stack-data/warehouse.duckdb` |
| Producers | Airflow OpenLineage provider (every task; Python tasks declare OpenLineage `Dataset` objects as `inlets`/`outlets`); Cosmos (dbt node datasets). The R4 fallback emitter wasn't needed |
| Dataset names | `warehouse.<schema>.<table>` (the DuckDB catalog name from the file, as the dbt processor emits it). The Python tasks' declared datasets use the same names, so the graph connects |
| UI | `http://localhost:3000` (namespace `aurora`) |

## Guarantees (tested by `test_lineage_graph`, `test_lineage_outage`)

1. Every task of a finished run has a COMPLETE (or FAIL) event in Marquez, under one parent run per DAG run (FR-009).
2. `agente.executar` has inputs `gold.campaign_daily`, `gold.source_health` and `meta.batch_status`, and outputs `ops.change_log`, `ops.approval_queue` and `ops.campaigns` (FR-010).
3. The `agente.executar` run carries the custom run facet (from `stack/dags/_lineage_facets.py` via `[openlineage] custom_run_facets`):
   ```json
   {"agentready_trace": {"_producer": "<openlineage-python client URL>", "_schemaURL": "urn:agentready:facet:trace:1.0.0", "trace_id": "<same as ops.change_log.trace_id>"}}
   ```
4. The path `bronze.conversions` → … → `agente.executar` exists in Marquez's lineage graph (US3 AS3).
5. Re-running the same day creates new **runs** of the same jobs, not new jobs (edge case "re-runs").
6. With Marquez stopped, the DAG run finishes with the same task states and decisions, plus the `linhagem indisponível` warning (FR-013).

## Not emitted (partial replacement, FR-014)

`métrica net_revenue|roas|cac|orders`, `tool get_campaign_performance|adjust_campaign_budget`, `guarda de frescor (semântica)` and `pré-condição dados_frescos`. These belong to the semantic layer and MCP, which still come from the default track. `agentready lineage` still shows them.
