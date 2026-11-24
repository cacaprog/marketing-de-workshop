# Phase 0 Research: Stack Track (Phase 1)

Date: 2026-11-24. Versions were checked against the official docs and release notes on that date.
Exact patch versions are locked when the image is built (see R10).

## R1. Orchestrator version and packaging

- **Decision**: Apache Airflow **3.3.2** (`apache/airflow:3.3.2-python3.12`), with **LocalExecutor**
  and Postgres as the metadata DB. Services: `postgres`, `airflow-init`, `airflow-apiserver`,
  `airflow-scheduler`, `airflow-dag-processor`. There is no Celery or Redis, and no triggerer (see R4).
- **Rationale**: 3.3.x is the newest patch-stable line; 3.3.2 was released 2026-09-17. It has the
  scheduler-managed `awaiting_input` state for human-in-the-loop tasks, so no triggerer or worker
  slot is held while a task waits. LocalExecutor keeps the stack within about 8 GB of RAM.
- **Alternatives considered**: 3.4.0 (2026-11-06) is too new to rely on for a live demo; we can
  upgrade once 3.4.1 is out. CeleryExecutor adds Redis and a worker for no teaching value.
  Dagster's asset model fits the medallion layers better, but the user chose Airflow.

## R2. dbt in Airflow

- **Decision**: **astronomer-cosmos ~=1.14** with `DbtTaskGroup`, `ExecutionMode.LOCAL`, and
  `dbt_executable_path` pointing at a separate dbt virtualenv inside the image, and
  `LoadMode.DBT_LS`, which reads the project with `dbt ls` when the DAG is parsed, so no
  `manifest.json` has to be committed.
- **Rationale**: Cosmos 1.10+ supports Airflow 3, and 1.14 (2026-04-07) is the latest release
  we confirmed. It renders each dbt model and test as its own Airflow task, which is what makes
  each stage inspectable (FR-005). Keeping dbt in its own venv avoids dependency conflicts with
  Airflow.
- **Alternatives considered**: a single `BashOperator` running `dbt build` loses per-model
  visibility. `ExecutionMode.VIRTUALENV` rebuilds the venv on each run, which is slow.

## R3. Transformations: dbt-core + dbt-duckdb

- **Decision**: dbt-core 1.10.x with the dbt-duckdb adapter, both locked to versions that support
  **duckdb 2.0.1**, the version already in the root `uv.lock`. A custom `generate_schema_name`
  macro makes models land in the exact schemas the agent reads: `silver`, `quarantine`, `meta`
  and `gold`.
- **Rationale**: all three venvs open the same warehouse file, so they must share one DuckDB
  file-format version. DuckDB refuses to open a file written by a newer version.
- **Alternatives considered**: SQLMesh is a strong option but less widely used, and the user
  named dbt.

## R4. Human-in-the-loop approvals

- **Decision**: use `HITLOperator`, not `ApprovalOperator`, with options `["Aprovar", "Rejeitar"]`,
  `defaults=["Rejeitar"]`, `response_timeout` read from `stack/config/stack.yaml` (default
  `20h`), `assigned_users` set to the approver user, and a Markdown `body` rendered from the
  request. Each request is one mapped task (`.partial().expand_kwargs()`). A downstream mapped
  task, `apply_decision`, always runs (trigger rule `all_done`) and applies or records the outcome
  through `agentready.capabilities`.
- **Findings (provider source, 1.22.0)**: the operator returns
  `{chosen_options, params_input, responded_at, responded_by_user}`. `subject` and `body` are
  Jinja-templated, and `body` supports Markdown. Without `defaults`, a timeout fails the task with
  `HITLTimeoutError`. On Reject, `ApprovalOperator` **skips downstream tasks**, which would stop
  us from recording rejections. That's why we use the base operator.
- **Expiry detection (open point, resolved by design)**: the payload has no explicit timeout
  flag. `apply_decision` treats a response as **expired** when `responded_by_user` is empty or
  missing, or when `responded_at >= timeout_datetime`. A test pins this behavior
  (T-approval-expiry). If the provider adds an explicit flag, we switch to it.
- **Timeout vs. schedule**: with `max_active_runs=1`, a run whose approval is still waiting holds
  the next scheduled run in the queue. The default `20h` makes an unanswered 07:00 request expire
  at 03:00, before the next run, so an unanswered day never delays the next one. Manual demo runs
  that are left waiting do block later runs; the guide says to answer them or lower the timeout.
- **User identity (verified on the live stack, T050)**: `assigned_users=[{"id": "aprovadora", "name": "aprovadora"}]`
  works with SimpleAuthManager. `instrutor`, although an admin, gets HTTP 403 when answering.
- **Timeout payload (verified on the live stack, T050)**: on timeout the provider records
  `chosen_options = defaults` (`["Rejeitar"]`) with `responded_by = null`, so "no responding user"
  is the expiry signal. The approver's response through the REST API is
  `PATCH /api/v2/dags/{dag}/dagRuns/{run}/taskInstances/aprovacao.revisar/{map_index}/hitlDetails`.
- **Alternatives considered**: `ApprovalOperator(fail_on_reject=True)` makes rejection look like
  an error. A custom approvals web page duplicates the orchestrator UI.

## R5. Contract checks: what datacontract-cli can and can't do

- **Findings**: datacontract-cli 1.0.x reads ODCS v3 and tests at dataset level against DuckDB.
  `--include-failed-samples` returns only a sample of failing rows. `export dbt-models` and
  `dbt sync` turn a contract into dbt schema YAML with tests. There is no **row-level quarantine**
  and no **per-batch circuit breaker**, and both are required (FR-010, FR-011).
- **Finding during implementation (T002)**: `datacontract lint` rejected all three contracts
  (`timestamp` needs ODCS v3.1; `rule: validValues` and SLA `partitionBy` aren't ODCS forms). The
  contracts were migrated to v3.1.0 (`metric: invalidValues`, schema
  `customProperties.freshnessPartitionBy`); see plan Complexity Tracking.
- **Decision**: split the responsibilities:
  1. **datacontract-cli** runs `datacontract lint` on every ODCS file as the first gate; an invalid
     contract stops the run. `datacontract export dbt-models` generates
     `stack/dbt/aurora/models/silver/_contracts.generated.yml`. That file is generated at stack
     init and again before each run, and is never committed (constitution: shared sources are
     referenced, not copied). It defines the contract tests that dbt runs on the **Silver** tables
     as a defense-in-depth assertion: if quarantine missed something, the run stops before Gold.
  2. **Row-level quarantine and the circuit breaker** are dbt models. One dbt-duckdb **Python
     model per contract** (`contract_checked__<t>`) calls the existing rule compiler
     `agentready.contracts.violation_exprs()`, which stays the single place where ODCS rules become
     SQL. The quarantine rate per batch, the breaker, the Silver/Quarantine split and
     `meta.batch_status` are plain, readable SQL models.
  3. **Contract parameters for SQL models** (quarantine limit, SLA hours, freshness partition,
     missing columns) come from one Python model, `meta.contract_registry`, built from
     `contracts.load_all()` on every run. No limit is hard-coded or copied into dbt vars.
  4. **Freshness**: `gold.source_health` is a Python model that calls the shared
     `pipeline.freshness(con, now=reference_ts)`. Like `violation_exprs()`, the rule stays one shared
     function, which keeps parity exact; dbt owns materialization and ordering.
- **Rationale**: this keeps Block 1's lesson (quarantine by row, block by batch) and keeps ODCS as
  the only source of the rules (constitution: shared sources). Each tool does what it does well.
- **Alternatives considered**: hand-writing violation SQL in dbt duplicates the rules (rejected:
  breaks the single source of truth). Soda Core or Great Expectations also test at dataset level,
  so they don't fix the gap. Running only `datacontract test` on Bronze would mark the whole
  dataset as failed every morning.

## R6. Schema violation and keeping the last good state

- **Decision**: when `meta.contract_registry.missing_columns` isn't empty for a contract:
  1. `contract_checked__<t>` selects `batch_id, ingested_at` from Bronze, sets every contract
     column to a typed `NULL` and sets `violations = ['esquema: colunas ausentes: <cols>']`. Every
     batch then gets `rate = 1.0` and is `barred` with `rows = quarantined = COUNT(*)`, which matches
     `contracts._record_batches(schema_break=True)` with no special case in `batch_status`.
  2. `silver.<t>` and `quarantine.<t>` are `new_rows UNION ALL SELECT * FROM {{ this }} WHERE
     <schema_broken>`. When the contract is broken, `new_rows` is empty (Silver) or excluded
     (Quarantine), so both keep their last contents, matching the default track, which overwrites
     neither. `{{ this }}` here really is the target table; it is guarded with
     `adapter.get_relation(...)` for the first build.
- **Rationale**: this matches FR-012 and the default track. No model fails, so Cosmos still
  builds Gold on the last good Silver. (An earlier draft had the check model return `dbt.this`,
  but that is the check model itself, not Silver.)

## R7. "Needs attention" without a permanently red DAG

- **Decision**: a `data_quality_alert` task after the contract stage **fails** only when this run
  produced *new* blocked batches or schema violations, meaning batches ingested after the
  watermark of the last successful run (`ops.stack_watermark`). The main path doesn't depend on
  it (it's a leaf), so Gold and the agent still run on the last good data.
- **Rationale**: the old ga4 batch from 20 days ago is blocked permanently. Alerting on every
  blocked batch would turn every run red, and people learn to ignore alerts that are always on.

## R8. Concurrency and idempotency

- **Decision**:
  - `max_active_runs=1`, plus an Airflow pool `duckdb_writer` with 1 slot shared by every task
    that writes to the warehouse (FR-007). Host-side commands such as `make stack-parity` fail
    fast on DuckDB's file lock and say why.
  - **Agent ledger** `ops.agent_runs`: before running the agent, compute a fingerprint of the
    inputs (a hash of `gold.campaign_daily`, `gold.source_health`, the business date, the
    versions of the contracts and config, the effective autonomy override, the brain and the
    gullible flag). If a finished run with the same fingerprint exists, the agent step is skipped
    with the message "já decidido para estes dados" (FR-006, SC-007). Run settings are part of the
    fingerprint so that, for example, a `supervised` run on the same data isn't treated as a repeat.
  - **Retry after a partial apply**: if an unfinished run (`running`/`failed`) with the same
    fingerprint already applied changes or queued requests, the retry does **not** run the agent.
    It marks that run `failed_partial`, lists what was applied, and fails so a human can review
    (and roll back if needed). An unfinished run with no changes is simply re-run.
- **Rationale**: the existing guardrail `max_changes_per_campaign_per_day: 2` would still allow a
  second, identical run on the same day to change budgets again. The ledger is orchestration code,
  so the agent's rules stay untouched (Principle I).

## R9. Time, time zones and parity

- **Decision**: every container runs with `TZ=${TZ:-America/Sao_Paulo}`. The scenario is
  generated **inside** the stack, so stored timestamps and the agent's clock agree. The DAG passes
  `reference_ts` (the time the run started) to dbt as a var for `source_health`. The parity tool
  (`agentready-stack parity`) generates both warehouses from the same fixed `now`, runs both
  pipelines with that `reference_ts`, runs both agents in the same process and day, and compares
  normalized results: no UUIDs or wall-clock timestamps.
- **Rationale**: freshness SLAs are relative to "now" (spec edge case). `semantic.py` and
  `capabilities.py` use `current_date`, so both tracks have to run on the same calendar day.

## R10. Python environments inside the image

- **Decision**: one image (`stack/Dockerfile`, FROM the Airflow image) with three venvs, each
  locked with `uv`:
  - `/opt/venvs/dbt`: dbt-core, dbt-duckdb, plus `agentready` and `agentready_stack` installed
    with `--no-deps` and `pyyaml`, for the Python models. Shared Python helpers for dbt live in
    `agentready_stack.dbt_contracts`, never under `models/`: dbt treats every `.py` file there as a
    model, and Python models can't import neighbouring files. `agentready_stack/__init__.py` stays
    import-free so it loads in this venv, which has no Airflow, mcp or OpenTelemetry.
  - Python models read run-time values such as `reference_ts` from YAML `config:` blocks
    (`config: {reference_ts: "{{ var('reference_ts') }}"}`) with `dbt.config.get()`, because
    `var()` isn't available inside Python models.
  - `/opt/venvs/dcc`: `datacontract-cli` **without** the duckdb extra. Found during T002:
    datacontract-cli 1.2.x pins `duckdb<1.6`, which conflicts with 2.0.1. This venv only runs `lint`
    and `export dbt-models` and never opens the warehouse, so it doesn't need DuckDB at all.
  - `/opt/venvs/agent`: `agentready` (editable, from the read-only mount of the repo) plus the
    `agentready_stack` package. DAG tasks call it with `@task.external_python`.
  `duckdb==2.0.1` is pinned in every venv that opens the warehouse (dbt and agent).
- **Rationale**: agentready depends on `mcp` 2.x and `opentelemetry`, which may conflict with
  Airflow's own dependencies. Isolated venvs avoid that and still run the same source files
  (FR-003).

## R11. Auth for the workshop

- **Decision**: Airflow 3 `SimpleAuthManager` with two users that have fixed development
  passwords, stored in `stack/config/passwords.json` (gitignored; an example file is committed):
  `instrutor` (admin) triggers runs, and `aprovadora` (op) is the only `assigned_users` for
  approvals. This shows segregation of duties.
- **Rationale**: the approver's identity has to be recorded (FR-017). The no-login "all admins"
  mode would make every response anonymous.
- **Note**: the guide states this setup is only for local study (spec assumption).
