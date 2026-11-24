# Implementation Plan: Stack Track — Production-Shaped Version of the Workshop (Phase 1)

**Branch**: `001-stack-production-track` | **Date**: 2026-11-24 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/001-stack-production-track/spec.md`

## Summary

Add an optional `stack/` folder that runs the same Aurora Cosméticos scenario on standard
open-source tools: Airflow 3.3 (with Postgres metadata) orchestrates one daily DAG; dbt-core +
dbt-duckdb (through Cosmos) build the contract stage, Silver and Gold; datacontract-cli lints the
ODCS contracts and generates the dbt tests that check Silver; Airflow's human-in-the-loop operator
replaces the CLI approval queue. The agent, its capabilities, the semantic layer, the contracts and
the business config are **reused from the repository as-is** (read-only mount), so a parity check
can prove the decisions are identical (Principle I). Research found one real gap: no OSS tool does
row-level quarantine plus a per-batch breaker. The plan fills it with dbt models built on the
existing ODCS→SQL rule compiler ([research R5](research.md#r5-contract-checks-what-datacontract-cli-can-and-cant-do)).

## Technical Context

**Language/Version**: Python 3.12 (stack image); the default track stays on ≥ 3.11. SQL is DuckDB's dialect.

**Primary Dependencies**: Apache Airflow 3.3.2 (standard provider: HITL), astronomer-cosmos ~=1.14,
dbt-core 1.10.x + dbt-duckdb, datacontract-cli 1.0.x, duckdb 2.0.1 (pinned in every venv), uv
(locking); agentready (this repo, unchanged decision logic).

**Storage**: DuckDB single file `stack/data/warehouse.duckdb` (separate from the default track);
Postgres 16 for Airflow metadata only; trace JSONL in `stack/data/traces/`.

**Testing**: pytest in a one-off container (`make test`): dbt is run with `dbtRunner` against a
temporary warehouse; DAG integrity is checked with `DagBag`; approval outcomes are tested as pure
functions over HITL payloads; plus a parity test. The default suite (`uv run pytest`) runs unchanged.

**Target Platform**: Linux/macOS hosts with Docker Engine + Compose ≥ 2.14 (x86_64 and arm64 images).

**Project Type**: data pipeline + orchestration (containerized), added next to the existing CLI package.

**Performance Goals**: a full daily run (no human waits) in ≤ 5 min on 4 CPU; `make up` to healthy
in ≤ 15 min, not counting image downloads (SC-001).

**Constraints**: ≤ 8 GB RAM; fully offline after images are built; no credentials (the Claude brain
is opt-in); one writer on the warehouse; pt-BR for all user-facing text.

**Scale/Scope**: 6 campaigns × 30 days (~180 spend rows, ~10k conversions); 1 DAG, ~25 tasks;
2 human users.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Gate | Pre-research | Post-design |
|---|---|---|---|
| I. Agent is the constant | Stack runs the same `agent.py`/`capabilities.py`/`semantic.py`; parity check exists | ✅ FR-003/014/020 | ✅ read-only mount + `external_python` venv (R10); parity tool compares normalized decisions (R9). The only change to shared code is an additive `capabilities.expire_approval()` (operational, not a decision rule) |
| II. Safety in the backend | Text never authorizes; live re-check on approval; fail-safe expiry; R0–R3 | ✅ FR-016–018 | ✅ approval goes through `decide_approval` → `_execute_approved` (re-check); timeout → `expired`, nothing applied (approval-request.md) |
| III. Missing ≠ zero | Per-feed freshness, quarantine by row, block by batch, stale → no action | ✅ FR-010–013 | ✅ the dbt contract stage keeps row and batch semantics (R5/R6); `source_health` per `partitionBy` with `reference_ts` (data-model) |
| IV. Deterministic & offline by default | Stack optional, separate folder and state, default track untouched | ✅ FR-001/002 | ✅ `stack/` only; separate warehouse; rules brain by default; nothing added to the root `pyproject` |
| V. One test per promise | Tests for each Phase 1 promise; default suite unchanged; parity check | ✅ FR-021/022 | ✅ test matrix below; parity is both a test and a `make` target |
| VI. Every tool replaces a module | Replacement map; reject tools with no module | ✅ FR-024/026 | ⚠️ datacontract-cli is a **partial** replacement; Postgres is Airflow infrastructure. Both justified in Complexity Tracking |
| VII. Accurate claims | Known gaps documented | ✅ FR-025 | ✅ centavos gap (V7) and the partial datacontract-cli role documented in `stack/README.md` |

**Result**: PASS with 2 justified items (Complexity Tracking).

### Replacement map (goes into `stack/README.md`, FR-024)

| Tool | Replaces (default track) | Block |
|---|---|---|
| Airflow 3.3 (DAG, pools, schedule) | the stage order in `pipeline.run()`; `agentready setup` / `pipeline` / `backfill-meta` / `incident inject` sequencing (now DAG params) | 1, 5 |
| Airflow HITL operator | `agentready approvals` / `approve` / `reject` (the CLI approval queue) | 4 |
| dbt-core + dbt-duckdb | `contracts.apply()` materialization (Silver/Quarantine/batch_status), `pipeline.build_gold()`, `pipeline.write_health()` (materialization) | 1, 2 |
| astronomer-cosmos | the Python glue that ran pipeline steps in sequence (each model/test becomes an inspectable task) | 1 |
| datacontract-cli | the hand-rolled reading of contract types for Silver (`contracts.CASTS` assertions) → generated dbt tests; adds ODCS lint (new gate) | 1 |
| *(kept, shared)* `contracts.violation_exprs()`, `contracts.missing_columns()`, `pipeline.freshness()` | — the ODCS→row-predicate compiler and the freshness rule stay single shared functions, called from dbt Python models (no OSS equivalent; keeps parity exact) | 1 |

## Project Structure

### Documentation (this feature)

```text
specs/001-stack-production-track/
├── plan.md              # this file
├── research.md          # Phase 0: R1–R11 decisions
├── data-model.md        # Phase 1: tables, state machines, parity report
├── quickstart.md        # Phase 1: validation V1–V9
├── contracts/
│   ├── dag-interface.md
│   ├── approval-request.md
│   ├── commands.md
│   └── parity-report.schema.json
└── tasks.md             # Phase 2 (/speckit-tasks)
```

### Source Code (repository root)

```text
stack/                                   # NEW: the whole stack track lives here
├── README.md                            # pt-BR guide: run, replacement map, roadmap, known gaps
├── Makefile                             # up/down/reset/run/approvals/parity/test/contracts-sync
├── compose.yaml                         # postgres, airflow-init, apiserver, scheduler, dag-processor
├── Dockerfile                           # FROM apache/airflow:3.3.2-python3.12 + 3 uv-locked venvs
├── .env.example                         # TZ, AIRFLOW_UID, ports
├── requirements/
│   ├── dbt.txt  dcc.txt  agent.txt      # uv-compiled locks; duckdb==2.0.1 in all
├── config/
│   ├── stack.yaml                       # approvals (timeout, approvers), alert watermark, schedule
│   └── passwords.example.json           # SimpleAuthManager users (real file gitignored)
├── dags/
│   └── aurora_midia_diario.py           # the one DAG (contracts/dag-interface.md)
├── dbt/aurora/
│   ├── dbt_project.yml  profiles.yml
│   ├── macros/generate_schema_name.sql
│   └── models/
│       ├── sources.yml                  # bronze.*
│       ├── contrato/                    # tag:contrato
│       │   ├── contract_registry.py         # contract params (limit, SLA, partition, missing cols)
│       │   ├── contract_checked__campaigns.py
│       │   ├── contract_checked__ad_spend.py
│       │   ├── contract_checked__conversions.py
│       │   ├── batch_quarantine_rate.sql
│       │   ├── batch_status.sql
│       │   └── quarantine__{campaigns,ad_spend,conversions}.sql
│       ├── silver/                      # tag:contrato
│       │   ├── {campaigns,ad_spend,conversions}.sql
│       │   └── _contracts.generated.yml # datacontract-cli export, generated at init and run time (gitignored)
│       └── gold/                        # tag:gold
│           ├── {dim_campaign,campaign_daily}.sql
│           ├── source_health.py         # calls the shared pipeline.freshness()
│           └── _gold.yml                # config: reference_ts = var('reference_ts') for source_health
├── agentready_stack/                    # small package, installed in the agent venv (and --no-deps in the dbt venv)
│   ├── pyproject.toml
│   └── src/agentready_stack/
│       ├── __init__.py                  # import-free (loads in the dbt venv)
│       ├── dbt_contracts.py             # checked_relation(): ODCS rules → violations, for dbt Python models
│       ├── tasks.py                     # ingest, alert, run_agent (ledger), apply_decision, watermark
│       ├── approvals.py                 # HITL payload → outcome; request → form body (pt-BR)
│       ├── ledger.py                    # input fingerprint + ops.agent_runs
│       ├── parity.py                    # both tracks, normalized compare, report
│       └── cli.py                       # `agentready-stack parity|doctor`
├── tests/
│   ├── conftest.py                      # temp warehouse, dbtRunner fixture
│   ├── test_contract_stage.py           # quarantine, breaker, schema violation keeps last good
│   ├── test_gold_and_health.py          # no fan-out, per-feed freshness, NULL via semantic layer
│   ├── test_agent_stage.py              # stale refusal, injection refusal, ledger idempotency
│   ├── test_approvals.py                # approve/reject/expire/live-recheck outcomes
│   ├── test_dag_integrity.py            # DagBag import, stage order, pool, max_active_runs
│   └── test_parity.py                   # manha/pos_backfill/supervisionado → 0 diffs
└── data/                                # gitignored: warehouse, traces, postgres volume

src/agentready/capabilities.py           # +expire_approval() (additive; default track unaffected)
src/agentready/contracts.py              # reads ODCS 3.1 forms (invalidValues, freshnessPartitionBy); old forms still accepted
contracts/*.odcs.yaml                    # migrated to valid ODCS v3.1.0 (minor version bump)
docs/00-*.md, docs/01-*.md               # wording for the ODCS 3.1 forms + correction note
.gitignore                               # + stack/data/, stack/config/passwords.json, generated contract tests
```

**Structure Decision**: everything new lives under `stack/` (Principle IV). The repo root is
mounted read-only at `/opt/agentready` with `AGENTREADY_HOME=/opt/agentready`,
`AGENTREADY_DB=/opt/stack-data/warehouse.duckdb` and
`AGENTREADY_TRACES=/opt/stack-data/traces`. `settings.py` already reads these, so contracts,
config, corpus and code are shared without copies (FR-003). The only edit outside `stack/` is the
additive helper in `capabilities.py` and the `.gitignore` entries.

### Test matrix (FR-021 → tests)

| Promise | Test |
|---|---|
| Stage order, pool, single active run | `test_dag_integrity` |
| Row quarantine with reasons | `test_contract_stage::quarantines_rows_with_reasons` |
| Per-batch breaker | `test_contract_stage::bars_batch_over_limit` |
| Schema violation keeps last good Silver | `test_contract_stage::schema_break_keeps_last_good` |
| Missing is NULL, not zero | `test_gold_and_health::stale_feed_yields_null_metrics` |
| Stale feed → agent refuses | `test_agent_stage::no_action_on_stale` |
| Injection refused | `test_agent_stage::gullible_injection_blocked` |
| Approve / reject / expire / live re-check | `test_approvals::*` |
| Idempotency | `test_agent_stage::rerun_is_skipped_duplicate` |
| Parity | `test_parity::*` (SC-002) |

## Implementation Notes (deviations found while building)

| Planned | Built | Why |
|---|---|---|
| `@task.external_python` into the agent venv | Airflow `@task`s call `agentready-stack task <name>` (subprocess) in the agent venv; the last stdout line is the JSON result | Airflow 3's `external_python` support for a venv without Airflow couldn't be checked; the CLI avoids that, and an instructor can run the same commands by hand |
| `duckdb==2.0.1` in all three venvs | Only in venvs that open the warehouse (dbt, agent); the datacontract-cli venv has no DuckDB | datacontract-cli 1.2.x pins `duckdb<1.6`; it only runs `lint`/`export` |
| Cosmos ~=1.14 | Cosmos 1.16.0 resolved (within `~=1.14`); `InvocationMode.SUBPROCESS` set on both execution and render configs | 1.16 defaults to in-process dbtRunner, but dbt lives in its own venv |
| One generated tests file | One file per contract: `_contract__<name>.generated.yml` (gitignored); needs `dbt_utils` + `dbt_expectations`, installed by `dbt deps` at image build | the export is per contract; the packages keep runs offline |
| SQL models read contract params | `meta.contract_registry` also publishes each contract's Silver cast list and quarantine payload; macros fetch them with `run_query` | SQL can't read YAML; types still come only from the contracts |
| Ledger fingerprint over `gold.source_health` | Excludes `age_hours` (changes every minute); includes each feed's `status` | otherwise every re-run would look new |
| Ledger fingerprint over raw Gold rows | Money columns rounded to cents before hashing; regression test `test_float_noise_in_gold_is_not_a_new_decision` | **found in quickstart V4 on the live stack**: DuckDB's parallel sums change the last float digits on every rebuild, so an identical re-run looked new and the agent changed budgets a second time (the 2-changes/day guardrail allowed it). The local test had passed by luck (single-threaded build) |
| Base image paths/permissions as in the official docs | Venvs created from `/usr/python/bin/python3.12`; Cosmos/pytest installed with `uv pip install --python /home/airflow/.local/bin/python`; dbt packages in `/opt/dbt/packages` (dbt deletes and recreates the folder); `HOME=/home/airflow`; the init uses the official entrypoint with `bash -c` (it registers the arbitrary UID as a user); Makefile one-offs use `bash -c` | found while building the image with `AIRFLOW_UID=1000` |
| `agentready_stack` depends on `agentready` | No declared dependency | an unrelated `agentready` package exists on PyPI; the repo's package is installed alongside with `--no-deps` |

### Found while validating US3 on the live stack

- **The quality alert was hidden by Airflow's default retry.** The alert failed correctly, but its retry ran after the
  closing task had moved the watermark, saw nothing new and turned green. Fixed with `retries=0` on
  `contratos.alerta_qualidade`, guarded by `test_quality_alert_is_a_leaf`.
- **US3 tests were written after the behavior.** Quarantine, breaker, schema-break and freshness behavior was built in the
  Foundational phase, so T039/T040 lock it in rather than drive it. The lint gate and the alert were test-first.

### Found while validating on a clean checkout (T057)

- **Every stack task failed on a fresh clone.** `agentready.db.connect()` always created the repo's `data/`
  folder, which is read-only in the containers and absent from a fresh clone (git doesn't track the empty
  folder). The working copy already had it, so every earlier test passed. Fixed in `src/agentready/db.py`
  (create only the warehouse file's own folder; default track unchanged) with a regression test.
- V1–V9 then passed on a clean clone: `make up` 32 s, first run to the approval ~70 s, everything from
  `make up` through V8 in ~10.5 min (SC-001: ≤ 15 min). SC-006 (approver decides in < 1 min) needs a person.

## Complexity Tracking

| Violation / added complexity | Why needed | Simpler alternative rejected because |
|---|---|---|
| datacontract-cli is only a **partial** replacement (Principle VI): row-level rule SQL stays in `contracts.violation_exprs()` | No OSS validator does row-level quarantine plus a per-batch breaker (R5); dropping them would break Block 1 and Principle III | Hand-writing the rules in dbt SQL duplicates the ODCS rules (two sources of truth). Using only `datacontract test` blocks whole datasets, so every morning would be red |
| Postgres added with no default-track module to replace | It's Airflow's required metadata store, part of the orchestrator rather than a data tool | SQLite metadata isn't supported for multi-service Airflow 3 setups |
| Three Python venvs in one image | duckdb file-format compatibility and the dependency conflicts between Airflow, dbt, datacontract-cli and mcp (R10) | One shared env risks unresolvable pins; separate images per tool add build time and RAM |
| Python dbt models (5 small files: 3 contract checks, the contract registry, source health) next to SQL models | They're the only way to reuse the shared rule compiler and freshness rule, and to read contract parameters, from inside dbt without copying the contracts | A pre-dbt codegen step adds a hidden build artifact, which is harder to teach |
| Shared contracts migrated to ODCS v3.1.0 and `contracts.py` taught the new forms (found during T002; approved by the user 2026-11-24) | `datacontract lint` showed the contracts were invalid ODCS (v3.0.2 + `timestamp`, `rule: validValues`, `partitionBy` in the SLA); Principle VII forbids the false claim in docs/00 | Making lint a warning would keep invalid contracts and lose the generated `accepted_values` tests. `contracts.py` still accepts the old forms, and the default suite passes unchanged |
| New ops tables (`agent_runs`, `stack_watermark`) | Idempotency (FR-006) and new-only alerts (R7). The existing guardrail allows 2 changes per day, so it isn't enough | Relying on `max_changes_per_campaign_per_day` lets a repeated run change budgets again |
