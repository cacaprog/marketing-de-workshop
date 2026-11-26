# Implementation Plan: Stack Track Phase 4 — Live Ingestion, Policy as Code and Snapshots

**Branch**: `004-stack-ingestion-policy-snapshots` | **Date**: 2026-11-26 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/004-stack-ingestion-policy-snapshots/spec.md`

## Summary

Phase 4 replaces the last three hand-written parts of the stack track with production tools, without changing what
the agent decides:

1. **Data arrives from sources** ([R4](research.md#r4-mock-upstream-sources-fr-001-fr-002), [R5](research.md#r5-declarative-ingestion-with-dlt-fr-003fr-005-fr-007)).
   - A new `upstream` service (FastAPI) plays four source systems. It serves the scenario that the **shared
     generator** writes into the service's own store. The generator's behavior is unchanged; two functions are
     extracted. The stack's Bronze is no longer written by the
     generator.
   - Sources fail deterministically: stalled Meta, redelivered batches, transient 503s, pages, a source down.
   - **dlt** (declarative REST API source) loads each source, one task per source, into `bronze_raw` in the lake.
     It uses change detection plus replace, so Bronze always mirrors the source. `bronze.*` become views with
     today's exact columns.
   - Block 5 incidents happen **at the source**, through the shared `incidents.inject` on the source store.
2. **Snapshots** ([R1](research.md#r1-table-format-with-snapshots-fr-008-block-5)–[R3](research.md#r3-snapshots-checkpoints-time-travel-and-restore-fr-008fr-012)).
   - The data layers move to **DuckLake** (spec 1.1, bundled with the stack's DuckDB 2.0.1). Its catalog goes in
     the existing Postgres and its files on a local volume. There is no object store; MinIO is now source-only.
   - Operational state stays in `ops.duckdb`, so a time travel can't rewind budgets. One connection sees both by
     DuckDB name resolution, with **no `db.py` change**.
   - Named checkpoints map runs to snapshots. "Gold as of a decision" is one command. Incident resolve = source
     rollback + **a restore that is itself a new snapshot** (undoable).
3. **Policy as code** ([R7](research.md#r7-the-policy-evaluator-fr-013fr-018-clarification-q1--a), [R8](research.md#r8-opa-deployment-and-tests-fr-013-fr-015a-fr-017-fr-018)), clarification Q1 = A.
   - `capabilities.py` gathers facts as today and asks one replaceable **policy evaluator**. Locally that's today's
     Python, moved verbatim to the new `policy.py`. On the stack it's **OPA**, with the Rego policy reading the
     shared `config/guardrails.yaml` as data.
   - The two evaluators are kept equal by one shared case file. That file feeds both `opa test` and the
     equivalence test, plus parity's new `policy` section.
   - Fail closed.

Parity grows to report 2.2.0 (Bronze, policy, ingestion sections) and must stay at zero differences.

## Technical Context

**Language/Version**: Python 3.12 (stack image) and Rego v1 (OPA). The default track is ≥ 3.11 and unchanged in
behavior.

**Primary Dependencies**:
- **DuckDB 2.0.1** (existing pin) with the bundled **`ducklake`** and **`postgres`** extensions, preinstalled at
  build.
- **dlt 1.x** with the `ducklake` extra, in a new `ingest` venv (version pinned in the spike).
- **FastAPI** in the agent venv (uvicorn and Starlette are already there via mcp 2.x).
- **Open Policy Agent 1.21.0**, the static image (the spike confirms the version).
- Unchanged: Airflow 3.3.2, Cosmos 1.16, dbt-core 1.12 + dbt-duckdb, Elementary 0.26.1, Marquez 0.50.0, OTel
  Collector 0.166.0, Phoenix 22.0.1.

**Storage**:
- `stack/data/lake/`: DuckLake Parquet files.
- A new `ducklake` database on the shared Postgres: the lake catalog.
- `stack/data/ops.duckdb`: operational state. It replaces `warehouse.duckdb`; Bronze, Silver and Gold leave the
  file.
- `stack/data/upstream/fontes.duckdb`: the sources' store.

New ops tables: `ops.ingestion_loads`, `ops.lake_checkpoints`, `ops.lake_restores` ([data-model.md](data-model.md)).

**Testing**: pytest in the one-off container (`make test`), plus `opa test` in the `opa` image, plus the
equivalence test against a running OPA. Live checks (a real run fed by the sources, a source down, OPA down, restore
and undo) are added to `make test-live`. Parity is `make parity` (report 2.2.0). The default suite runs unchanged
(`uv run pytest -q`).

**Target Platform**: Linux/macOS with Docker Compose ≥ 2.14, x86_64 and arm64. The OPA image and the DuckDB
extensions are multi-arch, and the extensions are installed per arch at build.

**Project Type**: containerized data pipeline (extends `stack/`), plus one shared module (`policy.py`) and two
structural edits in shared code ([Complexity Tracking](#complexity-tracking)).

**Performance Goals**:
- Ingestion of all four sources in ≤ 60 s per run, including the scripted retry.
- `make gold-em` in ≤ 5 s.
- A restore in ≤ 30 s.
- A policy decision in ≤ 100 ms (2 s timeout, then fail closed).
- A full run within +90 s of Phase 3's.

**Constraints**:
- 8 GB free RAM minimum stays (estimated peak ~3.4 GB).
- Offline after build: extensions preinstalled, autoinstall off, OPA telemetry off.
- pt-BR for everything users see.
- No change to the agent's decision rules. `incidents.py`, `db.py`, `tracing.py` and `agent.py` are unchanged. The
  shared generator only gets `create_ops_tables(con)` and `seed_live_state(con, now)`
  extracted, with no behavior change.
- One writer at a time.

**Scale/Scope**:
- +2 services (`upstream`, `opa`), +1 Postgres database, +1 venv (`ingest`).
- DAG: the ingestion task group goes from 1 to 5 tasks (`parametros` + one per source).
- `upstream` publishes only `127.0.0.1:8000`; its admin port 8001 stays internal. dlt telemetry off.
- New stack modules: `warehouse.py`, `ingestion.py`, `upstream_app.py`, `lake.py`, `policy_opa.py`.
- Shared: `policy.py` (new); `capabilities.py` checks delegate to it.
- New commands: `snapshots`, `gold-em`, `restaurar`, `politica`; `incidente-resolver` changes; `test` and `parity`
  grow.

No NEEDS CLARIFICATION remain: research R1–R13 resolved them. Facts left for the **spike V-P4-0**:
- DuckDB catalog-name resolution (R2);
- dlt on DuckDB 2.0.1 + Postgres catalog, and the `timezone: false` hint (R5);
- dlt state restored from the destination (R5);
- dbt Python models and Elementary on DuckLake (R9);
- OPA's `prefix:path` data loading and the exact version (R8);
- DuckLake commit messages and native rollback (R3);
- disk use per run (R3);
- the OpenLineage namespace dbt-ol emits with `path: ops.duckdb` and the lake attached as `warehouse` (R2).

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Gate | Pre-research | Post-design |
|---|---|---|---|
| I. Agent is the constant | Same agent source; same decision rules; parity | ✅ FR-014, FR-015 (Option A) | ⚠️→✅ `agent.py`, `_gate`, `_execute_approved` and the autonomy ladder are unchanged. The **checks move verbatim** from `capabilities.py` into `policy.LocalEvaluator`, with the same ids, order and details; this is a structural change, justified below. The stack's OPA must match: the equivalence test plus parity's `policy` and `traces` sections fail on any difference |
| II. Safety in the backend | Text never authorizes; re-check on approval; fail safe; logged changes | ✅ FR-016 | ✅ OPA is evaluated at proposal **and** at approved execution (same call site). Unreachable or invalid OPA → `politica_avaliada` fails, so nothing executes. Snapshots never touch `ops` (separate file), so rollback stays through the change log |
| III. Missing ≠ zero | Stale/blocked never fine | ✅ | ✅ a source that's down → load `falhou`, Bronze unchanged, freshness goes stale on its own. No partial batch is ever committed (atomic load package). `sem_dados_novos` is a status, never 0 rows of data |
| IV. Deterministic & offline by default | Default track has no containers; stack optional | ✅ FR-019/020 | ⚠️ accepted (Complexity Tracking): shared code changes in three files; default behavior is unchanged, proven by the unedited suite + parity. The default track still runs with no containers or network. `LocalEvaluator` is the default, and the OPA client lives in `stack/`. Source failures are scripted per run id. Extensions are preinstalled with autoinstall off |
| V. One test per promise | A test per FR-021 promise; parity | ✅ | ✅ test matrix below. Parity is extended (2.2.0), and the existing sections are unchanged. The default suite must pass **without edits** after the two shared edits |
| VI. Every tool replaces a module | Replacement map | ✅ | ✅ FastAPI `upstream` → the Bronze writes of `generate.py`/`incidents.py` (stack). dlt → the static load and the `ingest` task. DuckLake → the single warehouse file + `meta.incident_backup` (**partial**: `ops` stays a DuckDB file, R13). OPA → the enforcement of `guardrails.yaml` |
| VII. Accurate claims | Sources; gaps | ✅ FR-023 | ✅ MinIO's status is cited with sources (R1). DuckLake 1.1 is "versão nova" (R13 #7). Eight gaps are documented (R13) |

**Result**: PASS, with 9 accepted items (Complexity Tracking), including two structural shared-code edits under Principles I and IV.

### Replacement map additions (go into `stack/README.md`, FR-023)

| Tool | Version | Replaces (default track) | Block |
|---|---|---|---|
| **Fontes simuladas (FastAPI)** — `upstream` | FastAPI 0.x | the stack's Bronze writes by `generate.py` (`generate()`, `backfill_meta()`) and by `incidents.inject/resolve`. The shared generator now writes **the sources**, not Bronze | 1, 5 |
| **dlt** (fonte REST API declarativa) | 1.x | the static scenario load and the `ingest` task: per-source loads with retries, paging, change detection and a load record | 1 |
| **DuckLake** (catálogo no Postgres) | spec 1.1 / DuckDB 2.0.1 | the single warehouse file for the **data layers** and the hand-made `meta.incident_backup`: snapshots, time travel and restore. *Partial:* operational state stays in `ops.duckdb` | 5 |
| **Open Policy Agent** | 1.21.0 | the enforcement of `config/guardrails.yaml` in `capabilities.py` (the stack's evaluator); the limits stay in the YAML | 3 |

## Project Structure

### Documentation (this feature)

```text
specs/004-stack-ingestion-policy-snapshots/
├── plan.md              # this file
├── research.md          # R1–R13
├── data-model.md        # sources, loads, lake layout, checkpoints, restores, policy facts/decision, incident mirror
├── quickstart.md        # V-P4-0 … V-P4-16
├── contracts/
│   ├── upstream-api.md        # source and admin endpoints, failure plan
│   ├── ingestion.md           # dlt config per source, manifest diff, Bronze views, load record
│   ├── policy-interface.md    # evaluator protocol, facts, OPA decision API, cases file, fail-closed
│   ├── lake-snapshots.md      # connection layout, checkpoints, gold-as-of, restore algorithm and guards
│   ├── commands.md            # Phase 4 delta
│   ├── dag-interface.md       # Phase 4 delta: tasks, params, assets, spans
│   └── parity.md              # report 2.2.0 delta
├── checklists/requirements.md
└── tasks.md             # /speckit-tasks
```

### Source Code (repository root)

```text
src/agentready/
├── policy.py                          # NEW (shared): Fatos, Evaluator protocol, LocalEvaluator (checks moved verbatim), describe(), evaluate(), loader from AGENTREADY_POLICY_EVALUATOR
├── capabilities.py                    # _common_checks/budget_checks: gather facts as today → policy.evaluate(); span gets policy.evaluator/version. _gate unchanged
└── generate.py                        # extract create_ops_tables(con) and seed_live_state(con, now) (same DDL, same rows); generate() calls them. No behavior change

stack/
├── README.md                          # replacement map, gaps (R13), roadmap Phase 4 ✅, URLs (:8000/docs), new commands, disk per run
├── Makefile                           # snapshots, gold-em, restaurar, politica; incidente-resolver; test (+opa test, equivalence); reset (+ducklake db, lake/, upstream/)
├── compose.yaml                       # + upstream, opa; env AGENTREADY_DB=ops.duckdb, STACK_LAKE_*, AGENTREADY_POLICY_EVALUATOR, OPA_URL
├── Dockerfile                         # + ingest venv; preinstall ducklake/postgres extensions to /opt/duckdb-extensions
├── postgres-init/03-ducklake.sql      # NEW: idempotent role + database ducklake
├── policy/
│   ├── guardrails.rego                # NEW: package agentready.guardrails, version, decisao
│   ├── guardrails_test.rego           # NEW: iterates data.casos
│   └── casos.yaml                     # NEW: one case list for opa test + pytest equivalence
├── ingestion/fontes.yaml              # NEW: dlt REST API source config per source
├── requirements/agent.in|txt          # + fastapi
├── requirements/ingest.in|txt         # NEW: dlt[ducklake], duckdb==2.0.1, pyyaml, opentelemetry-sdk + otlp-proto-http (same pins as agent.txt)
├── dbt/aurora/profiles.yml            # ops.duckdb + attach lake, database: warehouse (both profiles)
├── dbt/aurora/models/sources.yml      # unchanged names (bronze views)
├── dags/aurora_midia_diario.py        # ingestao: parametros + 4 per-source tasks with source inlets; params falhas_upstream, fonte_fora_do_ar; tag stack-fase-4
├── scripts/live_check.py              # + sources, source down, OPA down, restore/undo
├── agentready_stack/src/agentready_stack/
│   ├── warehouse.py                   # NEW: connect() = ops.duckdb + ATTACH 'ducklake:…' AS warehouse + USE warehouse; extension settings
│   ├── upstream_app.py                # NEW: public app :8000 (sources, /docs; 127.0.0.1 only) + admin app :8001 (internal) over fontes.duckdb; main() serves both
│   ├── ingestion.py                   # NEW: manifest diff, dlt run per source, Bronze views, ops.ingestion_loads, ingestao.carga span
│   ├── lake.py                        # NEW: checkpoints, snapshots listing, gold_as_of, restore (+guards), lake.* spans
│   ├── policy_opa.py                  # NEW: OpaEvaluator (HTTP, 2 s timeout, schema check, fail closed)
│   ├── tasks.py                       # ingest → parametros (upstream admin calls, incident mirror); checkpoints in alerta/resumo/agente; uses warehouse.connect
│   ├── incidents_cli.py               # resolve = upstream resolve + lake restore + TTR
│   ├── cli.py                         # + ingest-fonte, snapshots, gold-em, restaurar, politica
│   └── parity.py                      # stack side via upstream subprocess + file catalog + OPA; report 2.2.0
└── tests/
    ├── test_policy_equivalence.py     # NEW: casos.yaml through Local and OPA; mutation of each limit
    ├── test_policy_fail_closed.py     # NEW: OPA down/invalid → politica_avaliada fails, nothing executes, no hang
    ├── test_upstream_api.py           # NEW: endpoints, manifest, failure plan determinism, incidents at the source
    ├── test_ingestion.py              # NEW: Bronze == generator Bronze; planted problems intact; retries no dup; partial page; sem_dados_novos
    ├── test_lake.py                   # NEW: name resolution; no ops schema in lake; checkpoints; gold_as_of; restore + undo; guards
    └── test_parity_v22.py             # NEW: schema 2.2.0, bronze/policy/ingestion sections on 'manha'

docs/01-roteiro-do-instrutor.md        # stack notes for Blocks 1, 3, 5
docs/02-exercicios.md                  # stack variants: show /docs, policy test failing, restore
```

The default suite (`tests/`) is **not edited**. Shared `policy.py` gets its own default-track test module only if
needed, as a new file. Principle V allows new tests.

**Structure Decision**: extend `stack/` as Phases 1–3 did. Three shared files change: `capabilities.py` is edited
and `policy.py` is new, as the user decided in Q1; `generate.py` gets two functions extracted so the stack can create
and seed its `ops` tables without copying the DDL or the seed rows. Nothing else under `src/agentready/` changes.

### Test matrix (FR-021 promise → test)

| Promise | Test |
|---|---|
| Feeds come only from the sources | `test_ingestion.py` (Bronze filled from `upstream`; no generator call in the stack's ingest path) + `test-live` |
| Each planted problem reaches Bronze unchanged | `test_ingestion.py` (Bronze checksum == generator Bronze) + parity `bronze` section |
| Ingestion retries don't duplicate | `test_ingestion.py` (`falhas_upstream=todas`) |
| A failing page commits nothing; a source down is `falhou`, others load | `test_ingestion.py`, `test-live` (`fonte_fora_do_ar=ga4`) |
| Each incident works through its source | `test_upstream_api.py` (4 kinds) + parity incident scenarios |
| Snapshots listed; Gold as of a decision | `test_lake.py` (checkpoint ids; `gold_as_of` metric == span attribute) |
| Resolve restores a snapshot; the restore is undoable; guards | `test_lake.py`, `test-live` |
| A restore never changes live campaign state | `test_lake.py` (ops checksum before == after) |
| The policy gives the same checks as today | `test_policy_equivalence.py` + parity `policy` and `traces` |
| Each guardrail has allow/deny; a changed limit fails a test | `opa test` + `test_policy_equivalence.py::mutation` |
| The policy fails closed | `test_policy_fail_closed.py` + `test-live` (OPA stopped) |
| Default track unchanged | `uv run pytest -q` with no edits |

### Implementation order (for /speckit-tasks)

1. **Spike V-P4-0**: settle the eight open facts and pin dlt and OPA. Record the fallbacks taken.
2. **Foundational**:
   - `warehouse.connect()`;
   - Postgres `ducklake` database;
   - extensions in the image;
   - dbt profiles on the lake;
   - the `ops.duckdb` rename;
   - `test_lake.py` name-resolution tests.

   Everything still passes Phase 3's tests and parity with Bronze still written by the generator **into the lake**.
   This is a checkpoint.
3. **US1** (P1): `upstream_app` → `ingestion` → DAG per-source tasks → incidents at the source → lineage → parity
   `bronze`/`ingestion`.
4. **US2** (P2): checkpoints → `snapshots`/`gold-em` → restore with guards → `incidente-resolver`.
5. **US3** (P3): `policy.py` + the `capabilities.py` delegation (default suite unchanged) → Rego + cases → OPA
   service → `OpaEvaluator` → equivalence and fail-closed → parity `policy`.
6. **US4**: README, instructor script, exercises. Measure RAM (SC-008), disk per run, and time SC-010.

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|---|---|---|
| **Shared `capabilities.py` edited** (checks delegate to `policy.evaluate`), and a new shared `policy.py` (Principle I names `capabilities.py` preconditions as protected) | Clarification Q1 = A: only one call site in shared code makes OPA *the* decision on the stack while the agent source stays one. The comparisons move verbatim. Ids, order, details and the gate flow are unchanged, and the default suite passes unedited | *Second gate on the stack only* (Option B): it doesn't replace anything (Principle VI). *Advisory OPA* (Option C): the Block 3 claim would be false |
| Guardrail rules exist in **two forms** (Python `LocalEvaluator`, Rego) | The default track must stay offline with no binary (Principle IV), and the stack must be decided by OPA (FR-015) | *Rego only*: the default track would need OPA. *Python only*: no policy engine. Kept honest by one shared case file, the equivalence test and parity |
| Shared `generate.py`: `create_ops_tables(con)` and `seed_live_state(con, now)` extracted | On the stack the `ops` tables live in `ops.duckdb` while Bronze comes from the sources. The stack must create the same live-state tables (with the PK) without copying their DDL (constitution, shared sources) | *Copy the DDL into the stack*: two definitions that drift. *Call `_reset` on the stack connection*: it drops every schema, including the lake's `bronze`/`gold` through `USE warehouse`. *Run the whole generator into `ops.duckdb` and drop Bronze*: wasteful and confusing |
| Lineage namespace may follow the dbt connection file (`ops.duckdb`) instead of `warehouse.duckdb` (only if spike fact 8 finds it changed) | The DuckLake catalog is attached as `warehouse`, so dataset **names** stay identical, but OpenLineage derives the **namespace** from the dbt profile's `path` | *Keep the data layers in `warehouse.duckdb`*: no snapshots (FR-008). *Fake the namespace in the facets*: lineage would point at a file that no longer holds the data. If it changes, Phase 2's `test_lineage.py` constant is updated as a recorded identity change, not a weakened assertion |
| New service `upstream` | FR-001/002: sources that fail, page and redeliver over the network. It replaces the Bronze writes of `generate.py`/`incidents.py` on the stack | *Static files*: they can't fail or retry. *WireMock/Prism*: a second copy of the scenario (shared-sources rule) |
| New service `opa` | FR-015/017: the engine that decides, answerable directly | *OPA as a library/Wasm in Python*: it adds a runtime to the shared code path and hides the "policy service outside the agent" idea Block 3 teaches |
| New venv `ingest` | dlt brings its own dependency tree; the Phase 1 rule (R10 there) isolates each tool's dependencies | *dlt in the agent venv*: risks conflicts with mcp/anthropic and couples ingestion upgrades to the agent |
| `ops` stays a DuckDB file (**partial** replacement of the single file) | FR-011/Principle II: snapshots must never rewind budgets, and `ops.campaigns` needs its PK | *Everything in DuckLake, ops left out of restores*: it loses the PK, and one bug in the restore list could rewind money decisions |
| Replace-per-source sync instead of incremental | Sources withdraw and replace batches (`centavos`, `renomeacao`, `feed_parado`). Bronze must mirror the source for the Block 5 lesson and for parity | *Incremental append*: it keeps both the original and the replaced batch, so the contract would bar `centavos` by duplicate key and the lesson would invert. *Merge with deletes*: it needs tombstones the scenario doesn't have |
