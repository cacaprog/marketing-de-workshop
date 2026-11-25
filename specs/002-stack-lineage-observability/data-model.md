# Data Model: Stack Track Phase 2

Everything new lives in the **stack warehouse** (`stack/data/warehouse.duckdb`) or the **Marquez database**
(`marquez` on the stack's Postgres). The default track's warehouse and tables don't change (FR-018).

## Warehouse: new and changed tables

### `meta.distribution_by_batch` (new, dbt model, tag `contrato`)

The breaker input, computed **before** the breaker on the rows that passed the contract (R3).

| Column | Type | Notes |
|---|---|---|
| source | VARCHAR | `ga4`, `meta_capi`, … |
| batch_id | VARCHAR | |
| ingested_at | TIMESTAMP | `max(ingested_at)` of the batch |
| avg_ticket | DOUBLE | `avg(order_value_brl)` |
| baseline | DOUBLE | median of `avg_ticket` over all of the source's batches (the batch itself included, as in `distribution_by_batch()`) |
| ratio | DOUBLE | `avg_ticket / baseline` |
| history_points | INTEGER | number of batches for the source (R7) |
| out_of_band | BOOLEAN | `ratio NOT BETWEEN lo AND hi` **and** `history_points >= min_history` |

Only batches that weren't barred by the contract are included. A contract-barred batch can't be blocked a
second time.

### `meta.batch_status` (changed)

Adds `barred_by` VARCHAR: `contrato` | `distribuicao` | NULL (passed). `status = 'barred'` when the quarantine
rate is above the limit **or** (`var('block_on_distribution_anomaly')` and `out_of_band`). The contract reason
wins when both apply. Existing readers (`get_data_health`, the quality alert) only read `status`, so they work
unchanged. The quality alert now also fires for distribution-barred batches, which is the post-mortem's intent.

### `quarantine.conversions` (changed)

A batch barred by distribution adds its rows with `reasons = ['anomalia de distribuição: ticket médio fora da
banda']`, the same text as the default track.

### `silver.conversions` (changed)

Also excludes batches with `barred_by = 'distribuicao'`.

### `meta.observability_checks` (new, dbt model, tag `observabilidade`) — the verdict table

One row per pillar and target for the current run. It is rebuilt on every run, and Elementary keeps the
history (via the generic tests' results).

| Column | Type | Notes |
|---|---|---|
| pillar | VARCHAR | `frescor` \| `volume` \| `distribuição` \| `esquema` (the default track's labels) |
| target | VARCHAR | the default track's target strings: `conversions/ga4`, `conversions/ga4.order_value_brl`, `bronze.conversions`, `<dataset>/<partition>` |
| status | VARCHAR | `pass` \| `fail` \| `warn` (`warn` only for short history, R7) |
| observed | DOUBLE | row count, average ticket or age in hours; NULL for schema |
| baseline | DOUBLE | median or SLA hours; NULL for schema |
| ratio | DOUBLE | NULL when not applicable |
| detail | VARCHAR | pt-BR, the same wording as `observability.py` (e.g. `ticket médio do último lote … (101.3x)`) |
| reference_ts | TIMESTAMP | the run's reference time |

It is built from four models: `obs_frescor`, `obs_volume`, `obs_distribuicao` and `obs_esquema`, unioned. The
distribution pillar reports **the latest batch per source** (as `distribution()` does), on the post-breaker
Silver.

**Validation (generic tests, captured by Elementary):** `observability_check_passes` on each `obs_*` model.
Its `severity: error` runs in a separate leaf task (`observabilidade.testes`), so a failure is red in Airflow
and in the Elementary report without blocking the agent. The verdict status `warn` (short history, R7) is a
pass for this test.

### `elementary.*` (new, created by the Elementary package)

`elementary_test_results`, `dbt_run_results`, `dbt_models`, `dbt_tests`, etc. These are the package's own
tables. We only read them through `edr report`.

### `ops.stack_run_settings` (new, written by `ingestao.preparar`)

| Column | Type | Notes |
|---|---|---|
| dag_run_id | VARCHAR | |
| block_on_distribution_anomaly | BOOLEAN | the effective value |
| source | VARCHAR | `compartilhado` \| `override` |
| min_history | INTEGER | |
| decided_at | TIMESTAMP | |

The effective breaker setting from the spec. The run's summary and the guide's runbook read it.

## Marquez (OpenLineage) entities

| Entity | Name / namespace | Produced by |
|---|---|---|
| Job namespace | `aurora` | `AIRFLOW__OPENLINEAGE__NAMESPACE` |
| Jobs | `aurora_midia_diario.<task_id>` (Airflow), plus dbt nodes as child jobs from Cosmos | the provider's listener; Cosmos |
| Dataset namespace | `duckdb:///opt/stack-data/warehouse.duckdb` | the OpenLineage dbt processor; the Python tasks' declared assets |
| Datasets (named `warehouse.<schema>.<table>`) | `bronze.*`, `meta.batch_status`, `meta.distribution_by_batch`, `quarantine.*`, `silver.*`, `gold.campaign_daily`, `gold.source_health`, `meta.observability_checks`, `ops.change_log`, `ops.approval_queue`, `ops.campaigns` | as above |
| Run facet `agentready_trace` | `{"trace_id": "<id>"}` on the `agente.executar` run | `run-agent` (R4) |
| Run | one per Airflow task try; a parent run per DAG run | the listener |

**Required edges** (asserted by `test_lineage_graph`):

`ingestao.preparar` → `bronze.*` → contract-stage models → `silver.*` → `gold.*` → `observabilidade.*` and
`agente.executar` (inputs `gold.campaign_daily`, `gold.source_health`; outputs `ops.change_log`,
`ops.approval_queue`, `ops.campaigns`) → `aprovacao.aplicar` (outputs `ops.change_log`, `ops.campaigns`).

**Partial replacement (FR-014)**: the hand-written map's nodes `métrica *`, `tool *`, `guarda de frescor
(semântica)` and `pré-condição dados_frescos` aren't emitted by any pipeline step. They stay out of Marquez and
are listed in the guide.

## State transitions

**Batch** (extends Phase 1): `loaded` → `passed` | `barred(contrato)` | `barred(distribuicao)`. This is
re-evaluated on every run from Bronze. After `incident resolve`, the redelivered batch no longer exists, so it
leaves every state.

**Verdict** per pillar and target, per run: `pass` | `warn` | `fail`. There are no transitions inside a run;
the history comes from Elementary.

**Incident** (shared, unchanged): `open` (injected) → `detected` (`make incidente ACAO=detectar`) → `resolved`
(`ACAO=resolver`, which then triggers a run).

## Parity report (extended)

`parity-report.schema.json` 2.0.0 (see `contracts/`) adds `compared.observability`. Its items are keyed
`<pillar>|<target>`, with the `status` field compared after mapping `warn` → `pass`. The scenarios add
`incidente_centavos`, `incidente_renomeacao`, `incidente_lote_duplicado` and `incidente_feed_parado`.
