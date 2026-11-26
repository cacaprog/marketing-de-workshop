# Contract: DAG interface (Phase 4 delta)

DAG `aurora_midia_diario`. Only the changes are listed. Tags gain `stack-fase-4` and `bloco-3`.

## Params (new)

| Param | Default | Values | Effect |
|---|---|---|---|
| `falhas_upstream` | `padrao` | `padrao`, `nenhuma`, `todas` | the sources' failure plan for this run ([upstream-api.md](upstream-api.md#failure-plan)) |
| `fonte_fora_do_ar` | `nenhuma` | `nenhuma`, `ads`, `ga4`, `meta_capi`, `catalogo` | that source answers 503 for the whole run |

The existing `reset_scenario`, `backfill_meta` and `incident` keep their names and meaning. Their effect now happens
**at the source** through the `upstream` admin routes.

## Task group `ingestao` (was 1 task, now 5)

```text
ingestao.parametros ──► ingestao.ads ─────────┐
                    ├─► ingestao.ga4 ─────────┤
                    ├─► ingestao.meta_capi ───┼──► contratos.lint …
                    └─► ingestao.catalogo ────┘
```

- **`parametros`** (agent venv): validate params; `PUT /admin/falhas`; reset/backfill/incident through admin
  routes; mirror the incident to `ops.incidents`; on reset, recreate the stack's `ops` tables with the shared
  `generate.create_ops_tables(con)` and seed the live campaign state with the shared
  `generate.seed_live_state(con, now)`, then add a `reset` checkpoint; autonomy override; distribution breaker (Phase 2).
  It emits `ingestao.parametros` (Phase 3) with the added attributes `agentready.falhas_upstream` and
  `agentready.fonte_fora_do_ar`.
- **`<fonte>`** (ingest venv, `pool` as today, `retries=0`: dlt retries HTTP itself, and a task retry would hide a
  `falhou`):

  | Task | Inlet asset | Outlet assets |
  |---|---|---|
  | `ads` | `fonte://ads/investimento` | `bronze_raw.ad_spend`, `bronze.ad_spend` |
  | `ga4` | `fonte://ga4/conversoes` | `bronze_raw.conversions__ga4`, `bronze.conversions` |
  | `meta_capi` | `fonte://meta/conversoes` | `bronze_raw.conversions__meta_capi`, `bronze.conversions` |
  | `catalogo` | `fonte://catalogo/campanhas` | `bronze_raw.campaigns`, `bronze.campaigns` |

  These give one lineage node per source upstream of Bronze in Marquez (FR-007). The ga4 feed is no longer shown
  only as `bronze.conversions`.

## Checkpoint calls inside existing tasks

`contratos.alerta_qualidade`, `observabilidade.resumo` and `agente.executar` each call `lake.checkpoint` at their
start ([lake-snapshots.md](lake-snapshots.md#checkpoints)). The graph doesn't change.

## Environment (compose `x-airflow-common`)

```text
AGENTREADY_DB=/opt/stack-data/ops.duckdb
STACK_LAKE_CATALOG=postgres:dbname=ducklake host=postgres user=ducklake password=ducklake
STACK_LAKE_DATA=/opt/stack-data/lake/
UPSTREAM_URL=http://upstream:8000
UPSTREAM_ADMIN_URL=http://upstream:8001          # admin routes; internal network only (never published)
OPA_URL=http://opa:8181
AGENTREADY_POLICY_EVALUATOR=agentready_stack.policy_opa:OpaEvaluator
RUNTIME__DLTHUB_TELEMETRY=false                  # dlt: anonymous telemetry off (FR-020)
```

## Span catalog delta (Phase 3 stack tracer; never in the audit log)

| Span | When | Attributes | Status |
|---|---|---|---|
| `ingestao.carga` | each source task | `agentready.fonte`, `.status`, `.lotes_novos`, `.lotes_retirados`, `.linhas` (omitted if NULL), `.tentativas_http`, `.snapshot_id`, run attrs | ERROR when `falhou` (description = pt-BR reason) |
| `lake.checkpoint` | each checkpoint | `agentready.etapa`, `.snapshot_id`, `.incident_id` | OK |
| `lake.restauracao` | restore / refusal | `.de_snapshot`, `.para_snapshot`, `.novo_snapshot`, `.motivo`, `.por` | ERROR when refused |
| *(shared action span)* `tool.adjust_campaign_budget`, `tool.pause_campaign` | as today | **+** `policy.evaluator`, `policy.version` | unchanged rule; a fail-closed rejection is ERROR (as any failed precondition) |
