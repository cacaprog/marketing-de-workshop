# Data Model: Stack Track (Phase 1)

The stack has its own warehouse (`stack/data/warehouse.duckdb`), but it uses the **same schemas
and table names as the default track**. That way `semantic.py`, `capabilities.py` and the agent
run unchanged. The tables are tagged **[same]** when they keep the default track's shape and
meaning, **[dbt]** when dbt builds them now, and **[new]** when they're stack-only.

## Bronze (written by the ingest stage, `generate.py` in Phase 1) — [same]

| Table | Grain | Notes |
|---|---|---|
| `bronze.campaigns` | one row per campaign per batch | all columns VARCHAR, plus `batch_id`, `ingested_at` |
| `bronze.ad_spend` | one row per campaign per day per batch | raw strings |
| `bronze.conversions` | one row per order per batch | includes the duplicated ga4 batch and dirty rows |
| `meta.upstream_backlog` | Meta rows held back | released by the `backfill_meta` param |

Declared as dbt **sources** (`models/sources.yml`).

## Contract stage — [dbt]

| Model | Kind | Contents | Rule |
|---|---|---|---|
| `meta.contract_registry` | Python, table | `contract VARCHAR, contract_version VARCHAR, table_name VARCHAR, max_quarantine_rate DOUBLE, sla_hours DOUBLE (NULL if no latency SLA), partition_by VARCHAR (NULL if none), missing_columns VARCHAR[]` | built from `contracts.load_all()` and `contracts.missing_columns()` on every run; the only source of contract parameters for the SQL models |
| `contract_checked__<t>` | Python, `table` in schema `meta` | every Bronze row plus `violations: VARCHAR[]` | expressions come from `agentready.contracts.violation_exprs(contract)`; on a schema violation: every Bronze row with typed-NULL contract columns and the violation `esquema: colunas ausentes: <cols>` |
| `meta.batch_quarantine_rate` | SQL | `contract, batch_id, n, bad, rate, limit` | `rate = bad / n`; `limit = contract_registry.max_quarantine_rate` |
| `silver.<t>` | SQL, table | contract-typed columns plus `batch_id` | rows with no violations **and** a batch rate ≤ limit; casts use `contracts.CASTS`; on a schema violation it keeps its previous contents (`UNION ALL SELECT * FROM {{ this }}`) |
| `quarantine.<t>` | SQL, table | `payload JSON, batch_id, ingested_at, violations VARCHAR[], quarantined_at` | rows with violations, plus every row of a blocked batch with the reason `lote barrado pelo disjuntor: X% > Y%`; on a schema violation it keeps its previous contents |
| `meta.batch_status` | SQL, table | `contract, contract_version, batch_id, ingested_at, rows, quarantined, rate, status` | `status ∈ {passed, barred}` ("blocked" in the spec); on a schema violation every batch comes out `barred` with `rate = 1.0` and `rows = quarantined`, with no special case |

**Validation**: the generated `_contracts.generated.yml` (from datacontract-cli) adds dbt tests
on `silver.<t>`: not_null for required fields, accepted_values, a primary key that is unique, and
types. If any test fails, Gold doesn't build.

## Gold — [dbt], same semantics as `pipeline.build_gold` / `write_health`

| Model | Grain | Key rules |
|---|---|---|
| `gold.dim_campaign` | campaign | `conversion_source = CASE channel WHEN 'meta' THEN 'meta_capi' ELSE 'ga4' END` |
| `gold.campaign_daily` | campaign × day | conversions **aggregated before** the join (no fan-out); `orders`/revenue are `COALESCE(…, 0)` at row level, exactly as on the default track. *Unknown* is expressed through `source_health` plus the semantic layer's NULL guard, not by this table |
| `gold.source_health` | dataset × partition | a Python model calling the shared `pipeline.freshness(con, now=reference_ts)` (`reference_ts` comes from a YAML `config:` block in `models/gold/_gold.yml`, read with `dbt.config.get`): `last_success_ingest = max(silver.<t>.ingested_at)` per `partitionBy`; age in hours rounded to 1 decimal place; `fresh` if `age_hours ≤ sla_hours`, else `stale`; no rows means age ∞ and `stale` |

## Operational state — [same] unless marked

| Table | Purpose | Change |
|---|---|---|
| `ops.campaigns` | live ad-platform state | none |
| `ops.change_log` | every applied change; source for rollback | none |
| `ops.approval_queue` | agent requests | **status adds `expired`**; `decided_by` holds the Airflow username or `sistema:timeout` |
| `ops.autonomy_override` | global ladder override | none |
| `ops.agent_runs` **[new]** | idempotency ledger | `run_id VARCHAR, dag_run_id VARCHAR, business_date DATE, input_fingerprint VARCHAR, status VARCHAR ∈ {running, done, skipped_duplicate, failed, failed_partial}, trace_id VARCHAR, started_at TIMESTAMP, finished_at TIMESTAMP, report JSON` |
| `ops.stack_watermark` **[new]** | the last successful run's ingest watermark, used for "new" alerts (R7) | `last_success_ingest_max TIMESTAMP, dag_run_id VARCHAR, updated_at TIMESTAMP` |

### Approval request state machine

```
pending ──(human: Aprovar)──▶ approved ──▶ apply → executed | rejected (live re-check failed)
   │
   ├──(human: Rejeitar)──▶ rejected
   └──(timeout, no human)──▶ expired      # fail-safe: nothing is applied
```

Rules: a request leaves `pending` exactly once. `approved` always re-checks preconditions on
the live state (`capabilities._execute_approved`, unchanged). `expired` and `rejected` never touch
`ops.campaigns`.

### Agent run ledger

```
(start) ─▶ running ─▶ done
              │  └──▶ failed (task error; retry starts a new row)
              └─────▶ failed_partial (a retry found changes/requests this run already
                                      applied; the agent does NOT run again, a human resolves)
(start, fingerprint already done) ─▶ skipped_duplicate
```

The fingerprint covers the Gold tables, the business date, the contract/config versions, the
effective autonomy override, the brain and the gullible flag. Changing any run setting makes it a
new decision, not a repeat.

## Parity report — [new], produced by `agentready-stack parity`

```
{ reference_ts, business_date, scenario: "manha" | "pos_backfill" | "supervisionado",
  compared: { campaign_daily: {rows, diffs[]}, source_health: {rows, diffs[]},
              decisions: {items, diffs[]} },
  ok: bool }
```

A decision is normalized to `(campaign_id, action, status, new_daily_budget_brl, failed_check_ids)`,
with IDs, trace IDs and timestamps removed. JSON schema: `contracts/parity-report.schema.json`.
