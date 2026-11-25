# Implementation Plan: Stack Track Phase 2 — Lineage and Data Observability

**Branch**: `002-stack-lineage-observability` | **Date**: 2026-11-24 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/002-stack-lineage-observability/spec.md`

## Summary

This closes the two gaps Phase 1 documented: the `centavos` incident passes the contracts, and lineage and
observability still come from the default track. The work comes in three steps, in this order:

1. **Upgrade dbt-core from 1.10 to 1.12** (1.11 leaves support on 2026-12-18). The Phase 1 tests and the parity
   check must pass before anything else changes ([R1](research.md#r1-which-dbt-core-to-upgrade-to-us5-fr-019-delivered-first)).
2. **Observability inside dbt.** Four `obs_*` models rebuild the default track's median-ratio and schema rules
   on their own (they don't call `observability.py`). Generic tests record each verdict, and the **Elementary**
   package keeps their history and builds the web report. The **distribution breaker** moves into the contract
   stage, controlled by the shared guardrail and a per-run override
   ([R2](research.md#r2-data-observability-what-elementary-replaces-and-what-it-doesnt-fr-001fr-008-clarification-q2), [R3](research.md#r3-where-the-distribution-breaker-lives-fr-005-fr-006)).
3. **Lineage from the running pipeline.** The Airflow OpenLineage provider (already in the image) and Cosmos
   send events to **Marquez**. The agent step declares its datasets and carries its trace id
   ([R4](research.md#r4-lineage-emission-fr-009-fr-010-fr-013), [R5](research.md#r5-lineage-store-marquez-fr-011)).

The parity check gains an `observability` comparison and four incident scenarios. The agent is unchanged.

## Technical Context

**Language/Version**: Python 3.12 (stack image), DuckDB SQL; the default track is unchanged (≥ 3.11).

**Primary Dependencies**: dbt-core **1.12.x** (from 1.10.23), dbt-duckdb 1.11.1, duckdb 2.0.1; Elementary dbt
package **0.26.1** and `elementary-data[duckdb]==0.26.1` (in the dbt venv); Airflow 3.3.2 with
`apache-airflow-providers-openlineage` 2.20.1 and openlineage-python 1.53.0 (already installed); Cosmos 1.16.0;
**Marquez 0.50.0** (API + web images). The combination was resolved locally with no conflicts (R1).

**Storage**: the stack's DuckDB warehouse (new tables in [data-model.md](data-model.md); the `elementary`
schema); a new `marquez` database on the existing `postgres:16` service; the static report in
`stack/data/elementary/`.

**Testing**: pytest in a one-off container (`make test`), as in Phase 1: dbt is run against a temporary
warehouse, with a temporary Marquez for the lineage tests (they're skipped with a clear message if Marquez isn't
reachable, and `make test` always has it). The default suite (`uv run pytest`) runs unchanged.

**Target Platform**: Linux/macOS with Docker Compose ≥ 2.14 (x86_64 and arm64; the Marquez images are
multi-arch).

**Project Type**: containerized data pipeline (extends `stack/`).

**Performance Goals**: a daily run up to the approval pause in ≤ 5 min (SC-007). Elementary's per-invocation
hook cost is the main risk (R6, with a fallback).

**Constraints**: ≥ 4 CPU, **≥ 10 GB free RAM** (R9); offline after build (Elementary packages are installed at
build time); one writer on the warehouse (`edr report` runs in the `duckdb_writer` pool); pt-BR for every
user-facing message; Marquez never published on host port 5000.

**Scale/Scope**: the same scenario. +6 dbt models (1 contract-stage, 4 `obs_*`, 1 union), +4 generic tests,
+3 Airflow tasks, +3 services, +4 parity scenarios.

No NEEDS CLARIFICATION remain: research R1–R9 resolved them.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Gate | Pre-research | Post-design |
|---|---|---|---|
| I. Agent is the constant | Same agent code; parity covers decisions | ✅ FR-017/018 | ✅ no change to `agent.py`/`capabilities.py`/`semantic.py`. Parity still compares decisions in all 7 scenarios. The trace facet is emitted by the stack task, not the agent |
| II. Safety in the backend | Text never authorizes; fail-safe | ✅ | ✅ the breaker blocks in the data layer before Gold; a verdict step that errors stops the agent (FR-008); a lineage outage can't change decisions (FR-013) |
| III. Missing ≠ zero | Blocked data never reaches the agent | ✅ FR-005 | ✅ distribution-barred batches leave Silver and Gold; `warn` (short history) never blocks or passes as "fine". It's a visible warning |
| IV. Deterministic & offline by default | Default track untouched; stack optional | ✅ FR-018 | ✅ nothing changes outside `stack/` except the docs (README roadmap, instructor script). Elementary and Marquez images are pulled or built once and then run offline |
| V. One test per promise | Tests for every FR-016 promise; parity | ✅ | ✅ test matrix below; parity is extended, not replaced |
| VI. Every tool replaces a module | Replacement map | ✅ FR-020/023 | ⚠️ Elementary is a **partial** replacement (the rule stays ours, R2); Marquez's partial coverage of the hand-written map (FR-014). Both justified below. The report server and the `marquez` DB are infrastructure of the tools they serve |
| VII. Accurate claims | Gaps documented | ✅ FR-021 | ✅ known gaps: Marquez is active but its last tagged release is 0.50.0 (2024-10), the PG version Marquez documents differs from ours, Elementary isn't running its own anomaly statistics, the static lineage nodes are absent |

**Result**: PASS with 2 justified items (Complexity Tracking).

### Replacement map additions (go into `stack/README.md`, FR-020)

| Tool | Version | Replaces (default track) | Block |
|---|---|---|---|
| **Elementary** (dbt package + `edr report`) | 0.26.1 | `observability.report()` and `agentready observe`: running the checks, storing each result per run, history, report. *The rules stay ours* (the median-ratio bands, R2) | 5 |
| **dbt models `obs_*` + contract-stage breaker** | — | `observability.freshness/volume/distribution/schema()` and `block_anomalous_batches()` (as SQL inside the pipeline) | 5 |
| **OpenLineage** (Airflow provider + Cosmos) | 2.20.1 · 1.53.0 | `observability.LINEAGE` / `downstream()`: lineage emitted by what actually ran | 4, 5 |
| **Marquez** | 0.50.0 | `agentready lineage` (the tree in the terminal) → a browsable graph with run history | 4, 5 |
| *(new query)* `agentready-stack decisions` | — | `observability.decisions_since()` | 5 |

## Project Structure

### Documentation (this feature)

```text
specs/002-stack-lineage-observability/
├── plan.md              # this file
├── research.md          # R1–R9
├── data-model.md        # warehouse + Marquez entities, parity extension
├── quickstart.md        # V-P2-0 … V-P2-9
├── contracts/
│   ├── dag-interface.md             # Phase 2 delta
│   ├── commands.md                  # Phase 2 delta
│   ├── lineage-events.md
│   ├── observability-check.schema.json
│   └── parity-report.schema.json    # 2.0.0
└── tasks.md             # /speckit-tasks
```

### Source Code (repository root)

```text
stack/
├── README.md                          # replacement map, gaps, roadmap (Phase 2 done), Block 5 runbook, 3 URLs, 10 GB
├── Makefile                           # check 10 GB; observe, incidente, decisoes; parity scenarios
├── compose.yaml                       # + marquez-api, marquez-web, relatorio; OpenLineage env; marquez DB init
├── Dockerfile                         # dbt venv: dbt-core 1.12 + elementary; dbt deps incl. elementary at build
├── postgres-init/01-marquez.sql       # NEW: idempotent CREATE ROLE/DATABASE marquez, run by the one-off marquez-db-init service
├── requirements/dbt.in, dbt.txt       # dbt-core~=1.12.0, elementary-data[duckdb]==0.26.1
├── config/stack.yaml                  # + observability.min_history: 7
├── dags/aurora_midia_diario.py        # + param disjuntor_distribuicao; observabilidade group; inlets/outlets; tags
├── scripts/contracts-sync.sh          # (if needed, R1) normalize generated test args for dbt 1.12; elementary manifest upload
├── dbt/aurora/
│   ├── packages.yml / package-lock.yml   # + elementary-data/elementary 0.26.1
│   ├── dbt_project.yml                # + vars (block_on_distribution_anomaly, min_history, bands); elementary config
│   ├── profiles.yml                   # + `elementary` profile (same file, schema elementary)
│   ├── macros/observability_bands.sql # NEW: bands + min_history in one place (read from vars)
│   ├── tests/generic/observability_check_passes.sql   # NEW
│   └── models/
│       ├── contrato/distribution_by_batch.sql          # NEW (breaker input)
│       ├── contrato/batch_status.sql, quarantine__conversions.sql   # + distribution breaker
│       ├── silver/conversions.sql                      # + exclude barred_by='distribuicao'
│       └── observabilidade/                            # NEW, tag:observabilidade
│           ├── obs_frescor.sql  obs_volume.sql  obs_distribuicao.sql  obs_esquema.sql
│           ├── observability_checks.sql                # union → meta.observability_checks
│           └── _observabilidade.yml                    # tests (severity: error; run by the leaf observabilidade.testes)
├── agentready_stack/src/agentready_stack/
│   ├── tasks.py                       # ingest resolves breaker; observe(); lineage-check in close
│   ├── observe.py                     # NEW: verdict table → pt-BR table / ObservabilityAlert
│   ├── lineage.py                     # NEW only under the R4 fallback (emitter); the trace facet lives in dags/_lineage_facets.py
│   ├── incidents_cli.py               # NEW: detect/resolve/reveal/list, decisions --since
│   ├── parity.py                      # + observability comparison, 4 incident scenarios, warn→pass
│   └── cli.py                         # + task observe, incident, decisions, lineage-check
└── tests/
    ├── test_observability.py          # NEW
    ├── test_breaker.py                # NEW
    ├── test_lineage.py                # NEW (needs Marquez; make test starts it)
    ├── test_incident_cli.py           # NEW
    ├── test_dag_integrity.py          # + new tasks, order, leaves, param
    └── test_parity.py                 # + incident scenarios, observability

docs/01-roteiro-do-instrutor.md        # Block 5 on the stack track (pt-BR), pointing at the README runbook
```

**Structure Decision**: as in Phase 1, everything new stays under `stack/` (Principle IV). `src/agentready/`
doesn't change: the stack reimplements the rules and calls only `incidents.*` (shared lifecycle, not replaced)
and the agent. `config/guardrails.yaml` is read, not edited.

### Test matrix (FR-016 → tests)

| Promise | Test |
|---|---|
| `centavos`: contract passes, distribution fails | `test_observability::centavos_passes_contract_fails_distribution` |
| Breaker on → quarantined + barred + 0 rows in Gold | `test_breaker::on_quarantines_and_bars` |
| Breaker off → report only | `test_breaker::off_reports_only` |
| Per-run override wins for that run only | `test_breaker::override_is_per_run` + `test_dag_integrity::breaker_param` |
| Short history → `warn`, never blocks | `test_observability::short_history_warns` |
| One pillar per incident (×4) | `test_observability::incident_pillar[kind]` |
| No double quarantine when contract + breaker both fire | `test_breaker::contract_barred_not_requarantined` |
| Lineage for every step incl. agent + trace facet | `test_lineage::graph_has_agent_with_trace` |
| Run survives lineage outage | `scripts/lineage-outage-check.sh` (`make test-live`) |
| Re-run → new runs, not new jobs | `test_lineage::rerun_adds_runs_only` |
| Report build failure is a warning | `test_observability::report_failure_is_warning` |
| Verdict step error stops the agent | `test_dag_integrity::agent_depends_on_obs_models` |
| Verdict parity, 7 scenarios | `test_parity::*` (SC-003) |
| dbt upgrade keeps Phase 1 | the whole Phase 1 suite + parity at V-P2-0 |

## Complexity Tracking

| Violation / added complexity | Why needed | Simpler alternative rejected because |
|---|---|---|
| Elementary is a **partial** replacement (Principle VI): the median-ratio rules are our own dbt SQL | Clarification Q2: exact verdict parity with the rule taught in Block 5; Elementary's z-score anomalies flag different batches (R2) | Built-in anomaly tests break parity; calling `observability.py` from dbt replaces nothing and makes parity compare a function with itself |
| Marquez doesn't cover the hand-written map's semantic/MCP nodes (FR-014) | Those nodes aren't produced by any pipeline step; the semantic layer and MCP are still default-track | Copying the static map into Marquez as fake jobs would be the "hand-drawn" lineage FR-014 forbids |
| Three new services (`marquez-api`, `marquez-web`, `relatorio`) and +2 GB minimum RAM | Lineage store and UI (FR-011); serving the report (FR-004) | Airflow's asset view has no run history or OpenLineage; opening the report as a file from the host breaks on remote/VM hosts |
| A second database on the existing Postgres, created by a one-off `marquez-db-init` service | Marquez needs Postgres; reusing the service saves ~100 MB and a container; the one-off init works on existing volumes (an initdb script runs only on an empty one) | A separate `postgres:14` is kept as the fallback if Marquez 0.50 migrations fail on 16 (R5) |
| `edr` installed in the dbt venv (not a 4th venv) | It runs dbt internally, so it needs the same dbt-core/adapter/duckdb; the resolve is clean (R1) | A separate venv would duplicate dbt and the duckdb pin with no isolation gain |

## Implementation Notes (deviations and findings while building)

### Phase 1 gate: dbt upgrade (T001–T006, 2026-11-25)

- Locked: **dbt-core 1.12.7**, dbt-duckdb 1.11.1 (unchanged), duckdb 2.0.1, dbt-adapters 1.24.6. The packages
  `dbt_utils 1.4.1`, `dbt_expectations 0.10.10` and `dbt_date 0.21.0` install and parse unchanged.
- `dbt parse --show-all-deprecations` on the generated contract tests: **no deprecations**, so
  `contracts-sync.sh` needs no post-processing (R1 risk 1 didn't happen).
- `doctor` now prints whether dbt-core is in active support (`MIN_DBT = (1, 12)`). It warns and doesn't fail.
- Gate results: `make test` 37 + 8 passed (2 min 43 s); default suite 18 passed; `make parity SCENARIO=todos`
  0 differences in `manha`, `pos_backfill`, `supervisionado` (21 s).
- dbt 1.12 prints a "dbt v2 is available" note on `--version`. This is expected; v2 was rejected in R1.

### Phase 2 setup (T007–T016, 2026-11-25)

- **Marquez 0.50.0 runs on the existing `postgres:16`**: all 91 Flyway migrations applied (schema v74) in
  about 1 s. The R5 fallback (`postgres:14`) **isn't needed**.
- **OpenSearch had to be turned off.** Marquez 0.50.0's `marquez.dev.yml` enables search by default
  (`SEARCH_ENABLED` defaults to true, host `opensearch`). `SEARCH_ENABLED=false` keeps that heavy service out;
  lineage and run history don't need it. The DB user, password and name are fixed to `marquez` in that file,
  which matches `postgres-init/01-marquez.sql`.
- The `marquez` DB is created by a one-off `marquez-db-init` service (idempotent `\gexec`), not an initdb
  script, so it also works on an existing Postgres volume (T011).
- `relatorio` reuses the stack image with `python3.12 -m http.server`, so no extra image is needed.
- Idle memory of the new services: marquez-api ~210 MB (heap capped at 512 MB), marquez-web ~18 MB,
  relatorio ~11 MB. Peak RAM under a run is measured in T061.
- `make up` (rebuild with Elementary) took 64 s. Elementary 0.26.1 (CLI and dbt package) is installed; the
  lock file is regenerated.
- Not checked: whether the Marquez images also exist for arm64 (only amd64 was pulled here).

### US1 (T024–T042, 2026-11-25)

- **Default selector for the verdict tests (new `stack/dbt/aurora/selectors.yml`).** With `severity: error`
  (analysis A1), every plain `dbt build` would exit non-zero, because the scenario's morning *always* fails the
  Meta feed's freshness and volume on purpose. That would have broken the unchanged Phase 1 `dbt` fixture and the
  parity build (analysis U2). The tests carry the tag `veredito_observabilidade`, and a `default: true`
  selector leaves them out of runs without `--select`. The DAG's `observabilidade.testes` selects them
  explicitly. No Phase 1 code changed.
- **`dbt_date` declared in `packages.yml`.** dbt checks "declared packages == installed packages". Cosmos's
  temporary copy of the project falls back to `packages.yml` (3 declared vs 4 installed, because `dbt_date`
  comes in through `dbt_expectations`), so the DAG wouldn't import. Declaring it fixes both cases.
- **`edr report` needed three changes for an offline image:**
  1. `stack/config/edr/config.yml` with `run_dbt_deps_if_needed: false`, since `edr` only looks for packages
     in `<project>/dbt_packages` and would otherwise rerun `dbt deps` and wipe `/opt/dbt/packages`. The same
     file sets `anonymous_usage_tracking: false`.
  2. The internal `edr` dbt project's packages (`dbt_utils 0.8.6` and `elementary 0.26.1`) are installed at
     image build.
  3. `EDR_INTERNAL_TARGET_PATH=/tmp/...`, because site-packages isn't writable under the container's UID.
- **The registry publishes `physical`, `columns` and `required_columns`** (for `obs_esquema`), as planned in
  T034.
- `obs_esquema` is a Python model. It needs `session.cursor()` for each query, because DuckDB refuses a
  second `execute` while results are pending.
- **The verdict detail strings match the default track word for word.** DuckDB's `format('{:,.2f}')`/
  `'{:.1f}'` produce the same text as Python's. On the clean morning, `make observe` printed the same 11 rows
  as `agentready observe`.
- **Live V-P2-1:** the morning run reached the approval pause in **142 s** (SC-007: ≤ 5 min). `testes` and
  `resumo` are red (the Meta feed is stale by design), and the agent still ran. The Elementary report records
  `obs_frescor` and `obs_volume` as **failures** (not warnings), and the other two pillars as passed.
- **`make test` now takes ~9 min** (56 + 13 tests, previously 37 + 8 in 2 min 43 s). That comes from the new
  scenario builds and from Elementary's setup and hooks in every `dbt build`.
- The `contratos.verificar.*_run` tasks show up as "removed" when the DAG is read while `contratos.lint`
  regenerates the contract tests. The real tasks (`*.run`/`*.test`) all ran. This is the Phase 1 behavior
  already described in the README.
- **Not validated live yet:** V-P2-2, V-P2-4 and V-P2-5. The validation run is waiting on a human approval,
  and with `max_active_runs=1`, new runs wait for it. Answering it as the approver is a person's decision,
  not the agent's.

### US2 (T043–T046, 2026-11-25)

- **`make parity SCENARIO=todos`: 7 scenarios, 0 differences**, including 11 observability verdicts per
  scenario. It passed on the first try, before any tuning (1 min 54 s).
- **Phase 1 compatibility kept without touching its tests:**
  - `parity.SCENARIOS` stays the Phase 1 tuple, because the Phase 1 test validates every scenario in it
    against the 1.0.0 schema, which only allows those 3 names.
  - The incidents are in `INCIDENT_SCENARIOS`; `ALL_SCENARIOS` is what `todos` runs.
  - `compare()` still returns the 1.0.0 report.
  - The new `compare_full()` adds `compared.observability` (2.0.0) and is used by the CLI and the new tests.
- The new tests are in a new file, `tests/test_parity_phase2.py`. A session-level cache in `conftest.py` around
  `parity.run_side` keeps the Phase 1 and Phase 2 files from building the same scenario twice.
- The stack side of parity now passes the **shared** breaker setting, the bands and `min_history` as dbt vars
  (never the per-run override). `STACK_PARITY_EXTRA_VARS` exists only for the band-drift test.

### US3 and US4, built (T047–T060, 2026-11-25)

- **No fallback emitter (R4).** The provider passes OpenLineage `Dataset` objects in `inlets`/`outlets`
  straight through (`ExtractorManager.convert_to_ol_dataset`), and Airflow 3 serializes them. The Python tasks
  declare `Dataset(namespace="duckdb:///opt/stack-data/warehouse.duckdb", name="warehouse.<schema>.<table>")`.
  These are the names Cosmos/dbt already emit, so the graph connects. `duckdb://` Assets would have been dropped
  (no converter for that scheme).
- The paused validation run already showed in Marquez the whole dbt chain (Bronze → contract stage → Silver →
  Gold → the five `obs_*` models), 37 jobs in namespace `aurora`.
- The trace facet lives in `stack/dags/_lineage_facets.py` (Airflow's env can't import `agentready_stack`),
  listed in `dags/.airflowignore`. `agentready_stack/lineage.py` holds only the Marquez health check and the UI
  link (not an emitter).
- **The live lineage check is `scripts/lineage_live_check.py`** (`make test-live`), not a `.sh`. It runs three
  `shadow` runs (A with Marquez up → `tests/test_lineage.py`; B with Marquez stopped; C as a re-run) and clears
  the autonomy override at the end. Shadow keeps the runs from waiting for a human. `make test` leaves out
  `test_lineage.py`.
- New non-live tests: `decisions --since` lists changes and the queue with the trace id; the closing task warns
  `linhagem indisponível` when Marquez doesn't respond.
- **A parity flake found and fixed.** `pos_backfill` (and potentially the incidents) compared `age_hours` of the
  backfilled or redelivered rows, which the shared code stamps with `now()`. The stack side gets to that step
  later (Elementary made its first build slower), so the age could fall on either side of the 0.1 h rounding
  (`-0.6` vs `-0.7`). The **parity harness** now pins those rows' arrival to `ref + 5 min` on both tracks.
  Shared code (`generate.backfill_meta`, `incidents.inject`) is unchanged (FR-018). This could already happen in
  Phase 1, just less often.
- README: Phase 2 rows in the replacement map plus the partial-replacement notes; gaps rewritten (`centavos`
  now detected; Marquez "projeto ativo; última versão publicada 0.50.0 (out/2024)"; ga4 shown as
  `bronze.conversions`; short history; verdict tests outside the default build); roadmap Phase 2 ✅; three
  URLs; new param and commands; a "Bloco 5 na trilha stack" section.
- `docs/01-roteiro-do-instrutor.md`: a short optional note in Block 5 pointing to the README.

### Live validation (T042, T050, T053, T054, 2026-11-25)

- **The first `make test-live` found three real problems:**
  1. **The trace facet wasn't reaching Marquez.** `AIRFLOW__OPENLINEAGE__CUSTOM_RUN_FACETS` was added to
     `compose.yaml` after the containers were last created, so they didn't have it (`dags/` changes took effect
     only because that folder is mounted). Fixed by recreating them with `make up`.
  2. **With Marquez stopped, a run took 437 s instead of 155 s**, because the OpenLineage HTTP client retries
     with backoff on every event. Fixed with `"retry": {"total": 0}` in the transport (the provider already
     never fails a task over lineage). `lineage_live_check.py` now also fails if the outage run takes more than
     max(300 s, 1.5× the normal run).
  3. **Contract test tasks disappeared from the DAG.** `contracts-sync.sh` deleted and regenerated the
     generated tests in place on every run. The dag processor re-read the DAG inside that window, and Cosmos
     cached the incomplete `dbt ls` in the Airflow Variable `cosmos_cache__…__contratos__verificar`. The cache
     never refreshed, because the files went back to the same content. Fixed at the root: the script now
     generates into a temporary folder and replaces only files whose content changed, using an atomic `mv`.
     One-time cleanup: the stale cache variables were deleted, and the tests (`campaigns.test`,
     `conversions.test`) came back. The README's troubleshooting table covers it.
- `lineage_live_check.py` leaves `contratos.alerta_qualidade` out of the state comparison: it depends on the
  watermark from the previous run, so two consecutive runs differ there by design, with or without Marquez.
- **Second `make test-live`: OK.** 3/3 lineage tests pass. The run with Marquez stopped took 145 s (vs 160 s
  with it up), with the same states and decisions and the `linhagem indisponível` warning. The re-run created
  new runs of the same 39 jobs (agent runs 4 → 5). **US3 AS4:** the lineage history stayed intact after
  `make up` recreated the containers.
- **The DAG run state is "failed" in normal mornings, by design:** the leaf checks (`testes`, `resumo`, the
  quality alert) are red because the Meta feed is stale. The agent, the approval and the closing step succeed.
  This is the Phase 1 alert behavior ("needs attention").
- **V-P2-2 live:** the contract approves `ga4-2026-11-24-redelivery`, and the distribution check fails with the
  default track's exact numbers (R$ 20,229.89 vs median R$ 200.45, 100.9x). The agent ran.
- **V-P2-4 live:** with `disjuntor_distribuicao: ligado`, the batch is `barred`/`distribuicao`, 240 rows are in
  quarantine with the default track's reason, 0 rows are in Silver, the ingest log reports the override and the
  next run went back to `compartilhado`. After the breaker the distribution check passes; ga4 freshness fails,
  because its last good load is now the previous day's batch.
- Live validation runs used `autonomy_override: shadow` so they wouldn't wait for approval. The approval in the
  clean-morning run (V-P2-1) was decided by a person in the UI.
- **V-P2-5 live:** `renomeacao` → schema (`bronze.conversions`) + ga4 freshness; `lote_duplicado` → ga4 volume;
  `feed_parado` → ga4 freshness + volume. Same pillars as the default track. Each run took ~150 s plus ~150 s
  queued behind the `resolver` rebuild.
- **T054 partly open:** the lineage path bronze → agent is checked through the Marquez API (`test_lineage.py`),
  but SC-005 asks for a **person** to do it in the UI in under 2 minutes, and nobody has timed that yet.
