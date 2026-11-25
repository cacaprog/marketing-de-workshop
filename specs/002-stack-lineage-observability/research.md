# Phase 0 Research: Stack Track Phase 2 (Lineage and Data Observability)

Date: 2026-11-24. Versions come from PyPI, GitHub releases and dbt hub, read on this date, and were checked by
**resolving them locally** (`uv pip compile`, Python 3.12) and by reading the installed source in the Phase 1
image. Exact patch versions are locked when the image is built (Phase 1 R10).

## R1. Which dbt-core to upgrade to (US5, FR-019; delivered first)

- **Decision**: **dbt-core 1.12.x** (resolves to 1.12.7). Keep **dbt-duckdb 1.11.1** (no change needed) and
  **duckdb 2.0.1** (pinned in every venv that opens the warehouse).
- **Rationale**: dbt Labs' version table: 1.10 is deprecated. 1.11 is in *critical support* and ends on
  **2026-12-18**, about three weeks from now. **1.12 is in active support until 2027-07-15**. A local resolve of
  `dbt-core~=1.12.0 + dbt-duckdb + duckdb==2.0.1 + elementary-data[duckdb]` succeeds with no conflicts
  (`dbt-core==1.12.7`, `dbt-duckdb==1.11.1`, `dbt-adapters==1.24.6`, `protobuf==6.33.6`,
  `elementary-data==0.26.1`). The installed dbt-duckdb 1.11.1 metadata declares `dbt-core>=1.8.0` and
  `duckdb>=1.0.0`. A web summary said dbt-duckdb needs `dbt-core>=1.12.5`; the wheel metadata doesn't say that,
  and the resolve shows it doesn't matter here.
- **Risks to check during the upgrade** (they are why the upgrade runs first, behind the Phase 1 tests and the
  parity check):
  1. Deprecations that 1.10 only warned about may now be errors. Main suspect: top-level test arguments in the
     tests datacontract-cli generates (`_contract__*.generated.yml`). If so, convert them in
     `contracts-sync.sh` (post-process the generated YAML to put the arguments under `arguments:`), not by hand.
  2. Make sure `dbt_utils 1.4.1`, `dbt_expectations 0.10.10` and `dbt_date 0.21.0` still parse. Their declared
     `require-dbt-version` ranges allow `<2.0.0`.
  3. Cosmos 1.16 runs `dbt ls` (LoadMode.DBT_LS) when it reads the DAG. Confirm the task list is the same
     (`test_dag_integrity`).
- **Alternatives considered**: **1.11**: it leaves support within weeks, so the gap reopens before the
  workshop's next run. **dbt v2 / dbt-oss** (first release 2026-09-14): a different engine and packaging. Cosmos
  and openlineage-integration-common still have v2-specific workarounds in their code (see R4), and
  dbt-duckdb's v2 support isn't confirmed. It's too much change for a phase that has to keep parity exact.

## R2. Data observability: what Elementary replaces, and what it doesn't (FR-001–FR-008, Clarification Q2)

- **Decision**: the **Elementary dbt package 0.26.1** (`elementary-data/elementary`, `require-dbt-version
  >=1.0.0,<3.0.0`) goes into the Aurora dbt project. It collects every dbt test result and run result into an
  `elementary` schema in the warehouse, keeps their history across runs, and the **`edr report`** CLI
  (`elementary-data[duckdb]==0.26.1`, in the dbt venv) builds the HTML report. **The verdicts come from our own
  models and generic tests** that copy `observability.py`'s rules exactly:
  - `distribution`: per batch, average `order_value_brl` / the median of the source's batch averages, band
    0.5–2.0 (the same SQL as `distribution_by_batch()`, on the post-breaker `silver.conversions`).
  - `volume`: rows from yesterday's business day per source vs. the median of the 14 days before (days with
    0 rows excluded), band 0.5–1.5, from `bronze.conversions`, with `current_date` exactly as the default track
    does.
  - `freshness`: one verdict per `gold.source_health` row (`status = 'fresh'`).
  - `schema`: per contract, extra or missing columns in the physical Bronze table, plus required columns more
    than 50% NULL in the latest batch. Columns come from `meta.contract_registry` (Phase 1), not from the
    contracts again.
- **Rationale**: Clarification Q2 makes the median-ratio rule the decision rule. Elementary's built-in tests
  (`volume_anomalies`, `column_anomalies`) use z-scores over training windows and wouldn't flag the same
  batches. Elementary still replaces what `observability.py` + `agentready observe` *do around* the rule: run the
  checks inside the pipeline, store each result per run, keep history, and show a report. This is a **partial
  replacement**, recorded like Phase 1's row-level quarantine (Principle VI, Complexity Tracking).
- **Why not call `observability.py` from a dbt Python model** (the Phase 1 pattern for `pipeline.freshness()`):
  then nothing would be replaced. The default track's module would still compute every verdict, and the
  parity check would compare a function with itself. Here, the parity check compares two independent
  implementations. That's what catches drift.
- **Alternatives considered**: Elementary's built-in anomaly tests (rejected by Q2). Running both, with the
  built-in tests for teaching only (option C in Q2, rejected). Soda Core or Great Expectations: whole-dataset
  checks with no per-run history store or report that fits dbt as well. They would add a second tool next to
  dbt.

## R3. Where the distribution breaker lives (FR-005, FR-006)

- **Decision**: the breaker is part of the **contract stage** (tag `contrato`). A new model,
  `distribution_by_batch`, computes each batch's ratio from the rows that passed the contract. `batch_status`,
  `quarantine__conversions` and `silver.conversions` read it together with the dbt var
  `block_on_distribution_anomaly`. When the breaker is on, batches outside the band are marked `barred`. Their
  rows go to quarantine with the reason `anomalia de distribuição: ticket médio fora da banda`, and they are
  left out of Silver. The verdict step (R2) runs later, on the final Silver.
- **Rationale**: the default track runs `block_anomalous_batches()` right after `contracts.apply()` and before
  `build_gold()`. Its report then reads the *post-breaker* Silver, so with the breaker on, the distribution
  pillar passes again. The stack copies both. dbt models are rebuilt from Bronze on every run, so a resolved
  incident (Bronze restored) drops out of the baseline naturally (edge case "incident resolved"). The same goes
  for a contract-barred batch, which can't be quarantined twice (edge case "breaker and contract both fire"):
  a contract-barred batch has no passing rows, so it gets no ratio.
- **Effective setting**: the `ingestao.preparar` task resolves it from the shared `config/guardrails.yaml`
  (`observability.block_on_distribution_anomaly`) plus the per-run DAG param `disjuntor_distribuicao`
  (`compartilhado` | `ligado` | `desligado`). It returns `{value, source}` as XCom, and the value is passed as a
  dbt var the same way Phase 1 passes `reference_ts`. The override applies to one run only, because XCom is per
  run. The parity check always uses the shared file.
- **Alternatives considered**: a post-hook that mutates Silver (as `block_anomalous_batches()` does). dbt
  models shouldn't mutate each other, and Cosmos would hide the mutation inside another task. A separate "gate"
  model between Silver and Gold would mean renaming the table the agent's semantic layer reads.

## R4. Lineage emission (FR-009, FR-010, FR-013)

- **Decision**:
  - **Transport**: the Airflow **OpenLineage provider 2.20.1** (already in the Phase 1 image, with
    `openlineage-python` and `openlineage-integration-common` 1.53.0) sends events over HTTP to Marquez:
    `AIRFLOW__OPENLINEAGE__TRANSPORT={"type":"http","url":"http://marquez-api:5000","endpoint":"api/v1/lineage","timeout":5}`,
    namespace `aurora`.
  - **dbt tasks**: Cosmos 1.16's `ExecutionMode.LOCAL` operator parses each dbt invocation's
    `manifest.json`/`run_results.json` with `DbtLocalArtifactProcessor` and attaches the input/output datasets
    to the task's OpenLineage COMPLETE event. Checked in the installed source (`cosmos/operators/local.py`). It
    works with dbt in a separate venv because it reads artifacts, not the dbt process. DuckDB datasets get the
    namespace `duckdb://<profile path>` = `duckdb:///opt/stack-data/warehouse.duckdb`
    (`openlineage/common/provider/dbt/processor.py`).
  - **Python tasks** (`ingest`, `run-agent`, `apply`, `observe`): they shell out to `agentready-stack`, so the
    listener can't see their datasets. They declare them as `inlets`/`outlets` (Airflow `Asset`s with the same
    `duckdb://…/<schema>.<table>` names). If the provider can't convert a `duckdb://` Asset (it only converts
    schemes that have a registered converter), the fallback is for the `agentready-stack` command to send its
    own OpenLineage events with `openlineage-python` in the agent venv. Those events carry a ParentRunFacet from
    the provider's `lineage_parent_id` macro, so they link to the Airflow task run. **Which path works is
    confirmed by the first lineage task** (an integration test asserts the agent job's inputs and outputs in
    Marquez).
  - **The agent step's trace id**: sent as a custom run facet `agentready_trace` (`{"trace_id": …}`) on the agent
    task's run (FR-010). This is what joins lineage to `ops.change_log.trace_id`. Mechanism: the provider's
    `[openlineage] custom_run_facets` option names a function in `agentready_stack.lineage`. On completion it
    reads the task's XCom `trace_id`, but only for `agente.executar`. Under the fallback path, the
    `run-agent` emitter adds the facet itself.
- **Outage behavior (FR-013)**: the provider's listener never fails a task when it can't send an event; it
  logs. On top of that: a 5 s HTTP timeout, and the closing task checks Marquez with `GET /api/v1/namespaces/aurora`
  and logs a visible pt-BR warning (`linhagem indisponível: …`) instead of failing. A test stops Marquez and
  confirms the run still finishes with the same decisions.
- **Alternatives considered**: `dbt-ol` (the OpenLineage dbt wrapper) would duplicate what Cosmos already
  sends. Airflow's built-in asset graph has no column/run history and no OpenLineage. Elementary's lineage covers
  dbt only and can't reach the agent.

## R5. Lineage store: Marquez (FR-011)

- **Decision**: **Marquez 0.50.0** (`marquezproject/marquez:0.50.0` API, `marquezproject/marquez-web:0.50.0`
  UI), README-labeled **RECOMMENDED** for OpenLineage 2-0-2. The API is internal at `marquez-api:5000` (admin on
  5001); the UI is on the host at **`http://localhost:3000`**. Marquez's data goes in a **second database,
  `marquez`, on the existing `postgres:16` service** (created by an init SQL script), so its history survives
  `make down`/`up` and is wiped by `make reset` (US3 AS4).
- **Rationale**: it's the roadmap's choice and the OpenLineage reference backend. Reusing the Postgres service
  saves a container and RAM. The 5000 port isn't published on the host (it clashes with AirPlay on macOS).
- **Honest gap (Principle VII)**: Marquez is an **active** project (a graduated LF AI & Data Foundation project,
  with an active-status badge, and still the development backend the Airflow OpenLineage docs point to). But
  **its last tagged release is 0.50.0 (2024-10-23)**; newer work is on `main`, unreleased. We pin the latest
  official release, not a `main` build. The README requires **PostgreSQL 14**. The guide must state exactly
  this: "active project, last tagged release 0.50.0 (Oct 2024)". Don't call it abandoned or "slow to release".
  Postgres 16 is a newer major
  version than the README names, so the first lineage task checks Marquez's migrations on 16. The fallback is
  a separate `postgres:14` service for Marquez (+~100 MB RAM).
- **Alternatives considered** (reviewed again 2026-11-24 at the user's request; Marquez kept):
  a **Marquez build from `main`** (newer code, but a commit pin and our own image instead of an official
  release); third-party forks with newer tags (e.g., a Rust-backend image), which aren't official;
  **DataHub** (accepts OpenLineage at `/openapi/openlineage/api/v1/lineage`, but ~5–8 GB more RAM for GMS,
  Elasticsearch, Kafka and MySQL; it would fold in the Phase 5 catalog, at about twice the minimum host);
  **OpenMetadata** (≥ 6 GB local; Phase 5 candidate); Elementary's lineage view (dbt-only, fails FR-009/FR-010).
  Because the emitters speak OpenLineage, moving to another backend later only changes the transport URL. Keeping the hand-written map was rejected by
  FR-014.

## R6. The Elementary report and the run summary (FR-004, Clarification Q3)

- **Decision**:
  - A new Airflow task, `observabilidade.resumo` (agent venv, `agentready-stack task observe`), reads the
    verdict table and prints the pt-BR five-pillar table (`pillar | target | ok | detail`, the same shape as
    `agentready observe`). It returns the verdicts as XCom. If any verdict is `fail`, it raises
    `ObservabilityAlert`. It is a **leaf** with `retries=0`, like Phase 1's quality alert, so the agent still
    runs (US1 AS2).
  - `observabilidade.relatorio` runs `edr report --file-path /opt/stack-data/elementary/index.html
    --profiles-dir … --project-dir …` in the dbt venv, in the `duckdb_writer` pool (single writer). A failure is
    logged as a warning and doesn't fail the run (edge case "report build fails"): the task catches the error
    and ends successfully with a pt-BR warning.
  - A small `relatorio` service (the stack image running `python -m http.server 8090 -d
    /opt/stack-data/elementary`, no new image) serves the report at **`http://localhost:8090`**.
- **Elementary's own profile**: `edr` needs a profile named `elementary`. Add it to `profiles.yml`, pointing
  at the same warehouse file with schema `elementary`.
- **Run cost**: every Cosmos task is a separate dbt invocation, so Elementary's `on-run-end` hook runs once per
  task. Set `disable_dbt_artifacts_autoupload: true` (upload the manifest once, from `contracts-sync.sh`) and keep
  the run and test results upload, since the report needs them. The time budget is checked against SC-007
  (≤ 5 min per run). If it's over budget, the fallback is Cosmos `TestBehavior.BUILD`, which folds tests into
  their model's task.

## R7. Short history (edge case, FR-015, Clarification Q5)

- **Decision**: the stack's volume and distribution verdicts are `warn` with detail `histórico insuficiente
  (N de M necessários)` when the baseline has fewer than `min_history` points: days with data for volume,
  batches for distribution. The default is **7**, set in `stack/config/stack.yaml` → `observability.min_history`.
  `warn` never blocks, even with the breaker on. The parity check maps stack `warn` → `pass`; that's the only
  mapping between verdicts.
- **Rationale**: the default track then reports `ratio = 1` / pass (`ratio = n / baseline if baseline else 1`,
  and a single batch is its own median). The three parity scenarios have 30 days of history, so the mapping
  never hides a real difference there. With a short history and a real out-of-band ratio, the default track can
  fail where the stack warns. The parity check then reports that difference, and the guide says so.

## R8. Incident lifecycle on the stack (US4 runbook, FR-022, TTD/TTR)

- **Decision**: new commands: `make incidente ACAO=detectar|resolver|revelar|listar`, which runs
  `agentready-stack incident …`. `detectar`, `revelar` and `listar` call the shared `incidents.mark_detected`,
  `reveal` and the incident table. `resolver` calls `incidents.resolve()` and then **triggers a DAG run** instead
  of `pipeline.run()`, because the default pipeline must never write the stack warehouse. TTD/TTR come from the
  shared incident record, as on the default track.
- **Decisions since T (FR-012)**: `make decisoes DESDE=<iso>` → `agentready-stack decisions --since`. It lists
  executed changes and queued requests since T, with trace id and a link to the agent run in Marquez. The query
  is a new one in `agentready_stack`; it doesn't call `observability.decisions_since()`, which belongs to the
  module being replaced.
- **Rationale**: Phase 1 only had `incident` as a DAG param (inject). Block 5 needs the whole lifecycle on the
  stack.

## R9. Host resources (FR-022, SC-007)

- **Decision**: raise the documented minimum to **4 CPUs and 10 GB of free RAM** (`make check`). Expected
  increase: Marquez API (JVM, heap capped at 512 MB with `JAVA_OPTS=-Xmx512m`), Marquez web (~100 MB), the
  report server (~40 MB), and `edr report` peaks inside the existing worker. Measured in the quickstart (V-P2-9),
  and the README table gets updated.
