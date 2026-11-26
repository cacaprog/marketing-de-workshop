# Data Model: Stack Track Phase 4

Names in `code` are physical. "Lake" = the DuckLake catalog attached as `warehouse`. "Ops" = `stack/data/ops.duckdb`
(catalog `ops`, schema `main`). See [research R2](research.md#r2-where-the-operational-state-lives-and-how-one-connection-sees-both-fr-011).

## 1. Storage layout

| Store | Holds | Snapshotted | Cleared by `make reset` |
|---|---|---|---|
| **Sources** `stack/data/upstream/fontes.duckdb` | what each source system has delivered. Written by the shared generator (`bronze.*` there = "source contents", `meta.upstream_backlog` = Meta's held days) and by the shared `incidents.inject/resolve` | no (it's the outside world) | yes |
| **Lake**: catalog in Postgres `ducklake`, files in `stack/data/lake/` | schemas `bronze_raw` (dlt), `bronze` (views), `quarantine`, `silver`, `gold`, `meta`, `elementary` | **yes**, every commit | yes (database dropped and recreated, folder emptied) |
| **Ops** `stack/data/ops.duckdb` | `campaigns`, `change_log`, `approval_queue`, `autonomy_override`, `agent_runs`, `stack_run_settings`, `incidents`, and new: `ingestion_loads`, `lake_checkpoints`, `lake_restores` | **never** | yes |

**Invariant**: the lake has no schema named `ops`. A test enforces it.

## 2. Source and delivery (in the sources store, served by `upstream`)

**Delivery batch**: `fonte` (`ads`, `ga4`, `meta_capi`, `catalogo`), `batch_id` (as the generator names it, e.g.
`ga4-2026-11-24`, `…-retry`, `…-redelivery`), `delivered_at` (= `ingested_at` of its rows), `rows`, `checksum`
(order-independent hash of all fields). The manifest for one source is the list of its batches now. A batch that
disappears from the manifest has been **withdrawn** by the source.

**Failure plan** (per run, in memory in `upstream`): `falhas_upstream` ∈ {`padrao`, `nenhuma`, `todas`},
`fonte_fora_do_ar` ∈ {`nenhuma`, `ads`, `ga4`, `meta_capi`, `catalogo`}, keyed by the `X-Execucao` header. The
same plan and run id always give the same failures.

## 3. Lake tables (new or changed)

| Table | Columns | Notes |
|---|---|---|
| `bronze_raw.ad_spend`, `bronze_raw.campaigns`, `bronze_raw.conversions__ga4`, `bronze_raw.conversions__meta_capi` | the source fields, all text, + `batch_id`, `ingested_at` (TIMESTAMP, naive) + `_dlt_load_id`, `_dlt_id` | written by dlt, `replace` per source |
| `bronze_raw._dlt_loads`, `_dlt_pipeline_state`, `_dlt_version` | dlt internals | restored with the lake, so dlt's state rewinds too |
| `bronze.ad_spend`, `bronze.campaigns`, `bronze.conversions` (**views**) | exactly today's Bronze columns | `* EXCLUDE (_dlt_load_id, _dlt_id)`; conversions = ga4 `UNION ALL BY NAME` meta_capi |
| `quarantine.*`, `silver.*`, `gold.*`, `meta.*`, `elementary.*` | unchanged from Phases 1–3 | now in the lake |

## 4. Ops tables (new)

**`ops.ingestion_loads`**: one row per source per run attempt.

| Column | Type | Rule |
|---|---|---|
| `load_id` | VARCHAR | `LD-<8 hex>` |
| `dag_run_id` | VARCHAR | |
| `fonte` | VARCHAR | ads / ga4 / meta_capi / catalogo |
| `status` | VARCHAR | `carregado` · `sem_dados_novos` · `falhou` |
| `motivo` | VARCHAR | pt-BR, required when `falhou` |
| `manifesto` | JSON | the source's batch list at request time |
| `lotes_novos`, `lotes_retirados`, `lotes_inalterados` | VARCHAR[] | manifest diff against the last `carregado` row of the same source |
| `linhas` | BIGINT | NULL when not `carregado` (never 0 for "unknown", Principle III) |
| `tentativas_http` | INTEGER | retries observed |
| `snapshot_id` | BIGINT | lake snapshot after the load. NULL unless `carregado` |
| `iniciado_em`, `terminado_em` | TIMESTAMP | |

Transitions: a load is created as `falhou` if any request exhausts its retries or the load package fails. It's
`sem_dados_novos` if the manifest equals the last `carregado` manifest; otherwise `carregado`. The next run compares
against the last **`carregado`** row, so a failed load is retried in full.

**`ops.lake_checkpoints`**: named points in the lake history.

| Column | Type | Rule |
|---|---|---|
| `checkpoint_id` | VARCHAR | `CK-<8 hex>` |
| `dag_run_id` | VARCHAR | NULL for checkpoints from commands |
| `etapa` | VARCHAR | `reset` · `ingestao.<fonte>` · `contratos` · `gold_observabilidade` · `agente` · `restauracao` |
| `snapshot_id` | BIGINT | `max(snapshot_id)` at that moment |
| `incident_id` | VARCHAR | the incident open at that moment, or NULL |
| `lotes` | VARCHAR[] | the batches this checkpoint covers: the manifest's `lotes_novos` for `ingestao.<fonte>`; NULL for layer stages |
| `criado_em` | TIMESTAMP | |

Layer checkpoints are per stage, not per dbt model: the contract stage covers quarantine + Silver, and
`gold_observabilidade` covers Gold + observability.

**`ops.lake_restores`**

| Column | Type | Rule |
|---|---|---|
| `restore_id` | VARCHAR | `RS-<8 hex>` |
| `de_snapshot`, `para_snapshot` | BIGINT | `para` = the target. The restore's own commit is recorded as a `restauracao` checkpoint |
| `novo_snapshot` | BIGINT | the snapshot the restore created |
| `por` | VARCHAR | actor (`instrutor` by default) |
| `motivo` | VARCHAR | e.g. `incidente INC-… resolvido` |
| `incident_id` | VARCHAR | nullable |
| `feito_em` | TIMESTAMP | |

**`ops.incidents`** (existing shape, now a **mirror**): the row is copied from the sources store at injection
(same `incident_id`, `kind`, `injected_at`, `batch_id`). `detected_at` and `resolved_at` are set on the stack.
TTD/TTR come from here (`incidents.metrics` works unchanged on it).

## 5. Snapshot (lake, read-only view of the format)

`ducklake_snapshots('warehouse')`: `snapshot_id`, `snapshot_time`, `schema_version`, `changes`. The stack's listing
joins it to `ops.lake_checkpoints` (label) and `ops.lake_restores`. A snapshot with no checkpoint is shown grouped
under the last checkpoint before it.

**Gold as of a decision**: decision key (trace id | `CHG-…` → `change_log.trace_id` | `REQ-…` →
`approval_queue.trace_id`) → `ops.agent_runs` (row with that trace id → `dag_run_id`) → the `agente` checkpoint of
that run → `snapshot_id` → `gold.campaign_daily AT (VERSION => snapshot_id)`.

## 6. Policy

**Facts** (`policy.Fatos`, built by the shared capabilities from the live state, unchanged queries):

| Field | Source today | Used by checks |
|---|---|---|
| `campaign_id`, `campanha_existe` | `_campaign()` | `campanha_existe` |
| `campaign_name`, `status`, `locked_by_human`, `objective`, `conversion_source` | `_campaign()` | `campanha_ativa`, `sem_trava_humana`, `objetivo_elegivel` |
| `justificativa` | argument | `justificativa_presente` |
| `frescor_status`, `frescor_idade_h` (NULL if no row) | `gold.source_health` | `dados_frescos` |
| `orcamento_atual`, `orcamento_novo`, `variacao_pct` | `_campaign()`, argument | `variacao_maxima`, `orcamento_minimo` |
| `soma_outras_ativas` | `ops.campaigns` | `teto_do_portfolio` |
| `alteracoes_hoje` | `ops.change_log` | `limite_de_alteracoes` |

**Limits**: `config/guardrails.yaml` (unchanged file). Locally it's read by `settings.guardrails()`. In OPA it's
loaded as `data.guardrails`.

**Policy decision**: `permitido` (bool), `checagens` = ordered list of {`id`, `ok`, `valores`} with ids in
today's order (budget checks only for `adjust_campaign_budget`), `versao`. It becomes the existing
`list[Check(id, passed, detail)]` via the shared `describe()`. Fail-closed = exactly one check
`politica_avaliada` (`passed=false`).

**Case** (`stack/policy/casos.yaml`): `nome`, `acao`, `fatos`, `esperado_falhas` (list of ids, empty = allowed).
Constraint: every check id appears in ≥ 1 case as passing and ≥ 1 as failing.
