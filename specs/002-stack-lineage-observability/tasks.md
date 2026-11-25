---

description: "Task list for Stack Track Phase 2 (lineage and data observability)"
---

# Tasks: Stack Track Phase 2 — Lineage and Data Observability

**Input**: Design documents from `/specs/002-stack-lineage-observability/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md

**Tests**: REQUIRED. FR-016 and constitution Principle V ask for one automated test per Phase 2 promise
(plan.md → "Test matrix"). In each story, write the tests first and confirm they fail before implementing.

**Organization**: tasks are grouped by user story. **Exception to priority order:** US5 (the dbt upgrade,
P5) is delivered **first**, as Phase 1, per Clarification Q1 and FR-019. Nothing else may start until its gate
(T006) passes.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel (different files, no dependency on an unfinished task)
- **[Story]**: US1–US5 from spec.md
- All paths are relative to the repo root. Everything new lives under `stack/` (plus docs).

## Global rules for every task (from the constitution and plan)

- **Do not edit `src/agentready/`** (FR-018, Principle I). The stack only *calls* `incidents.*`, the agent and
  the shared `guardrails()` reader. If a task seems to need a change there, stop and ask.
- **Do not call `agentready.observability`** from stack code, except in `parity.py` for the **default** side.
  The stack's rules are its own SQL (research R2).
- Every text a user sees (logs, Makefile messages, README, check details) is **pt-BR**. Verdict `detail` strings
  copy `src/agentready/observability.py` word for word.
- Shared sources stay read-only at `/opt/agentready`. Never copy them into `stack/`.
- Pin `duckdb==2.0.1` in the dbt and agent venvs. Pin `dbt-core~=1.12.0`, `elementary-data[duckdb]==0.26.1`,
  Elementary dbt package `0.26.1`, and `marquezproject/marquez(-web):0.50.0`.
- **Marquez wording** (README, logs): "projeto ativo; última versão publicada 0.50.0 (out/2024)". Never
  "abandonado" or "lento".

---

## Phase 1: User Story 5 — Transformation framework on a supported version (Priority: P5, delivered FIRST) 🚧 gate

**Goal**: dbt-core 1.10.23 → 1.12.x with zero behavior change (FR-019, research R1).

**Independent Test**: quickstart V-P2-0. `make test`, `uv run pytest -q` and `make parity SCENARIO=todos`
all pass, with 0 differences.

- [X] T001 [US5] In `stack/requirements/dbt.in` change `dbt-core~=1.10.0` to `dbt-core~=1.12.0` (keep `dbt-duckdb`, `duckdb==2.0.1`, `pyyaml>=6.0`) and recompile `stack/requirements/dbt.txt` with `uv pip compile --python-version 3.12 stack/requirements/dbt.in -o stack/requirements/dbt.txt`. Expect `dbt-core==1.12.x`, `dbt-duckdb==1.11.1`, `duckdb==2.0.1`. Update the header comment's version note
- [X] T002 [US5] Rebuild the image (`cd stack && docker compose build airflow-init`) and confirm `dbt deps` at build still installs `dbt_utils 1.4.1`, `dbt_expectations 0.10.10` and `dbt_date 0.21.0` with no `require-dbt-version` errors. If one fails, bump only that package within its compatible range in `stack/dbt/aurora/packages.yml` and regenerate `stack/dbt/aurora/package-lock.yml`
- [X] T003 [US5] Run `make contracts-sync`, then `dbt parse` in the dbt venv. If dbt 1.12 rejects the datacontract-cli-generated tests (e.g., top-level generic-test arguments), add a post-processing step to `stack/scripts/contracts-sync.sh` that moves those arguments under `arguments:` in every `stack/dbt/aurora/models/silver/_contract__*.generated.yml`. Never hand-edit the generated files
- [X] T004 [P] [US5] Update the dbt version expectations and messages in `stack/agentready_stack/src/agentready_stack/cli.py` (`doctor`) so they report and accept dbt-core 1.12.x
- [X] T005 [P] [US5] In `stack/README.md`, update the versions table (dbt-core `1.12.x`) and remove the "dbt-core 1.10 já está fora do suporte" item from "Lacunas conhecidas". If T001–T003 failed and 1.12 couldn't be used, write why instead (FR-019)
- [X] T006 [US5] **Gate (V-P2-0):** run `cd stack && make up && make test`, `uv run pytest -q` at the repo root, and `make parity SCENARIO=todos`. All must pass with **0 differences**. Record the versions and the result in plan.md → a new "Implementation Notes" section. Do not start Phase 2 until this passes

**Checkpoint**: Phase 1 behavior unchanged on a supported dbt.

---

## Phase 2: Setup (Shared Infrastructure)

**Purpose**: Elementary installed; Marquez, its UI and the report server running; OpenLineage configured. No
data logic yet.

- [X] T007 [P] Add `elementary-data[duckdb]==0.26.1` to `stack/requirements/dbt.in` (comment: "edr report; roda o dbt internamente, por isso no venv do dbt", research R6) and recompile `stack/requirements/dbt.txt`. Confirm `duckdb==2.0.1` is still the resolved version
- [X] T008 [P] Add `- package: elementary-data/elementary` `version: 0.26.1` to `stack/dbt/aurora/packages.yml`. In `stack/dbt/aurora/dbt_project.yml` add `models: elementary: +schema: elementary` and `vars: disable_dbt_artifacts_autoupload: true` (research R6). Regenerate `package-lock.yml`. Confirm `macros/generate_schema_name.sql` puts Elementary's models in the `elementary` schema
- [X] T009 [P] Add a second profile `elementary` to `stack/dbt/aurora/profiles.yml`: `type: duckdb`, the same `path` as `aurora`, `schema: elementary`, `threads: 1`
- [X] T010 [P] Add `observability:` to `stack/config/stack.yaml`: `min_history: 7`, `bands: {volume: [0.5, 1.5], distribution: [0.5, 2.0]}`, with a pt-BR comment saying the bands copy `VOLUME_BAND`/`DISTRIBUTION_BAND` in `src/agentready/observability.py` and that the parity check catches drift
- [X] T011 In `stack/compose.yaml` add a one-off `marquez-db-init` service (`postgres:16`, depends on `postgres` healthy, `restart: "no"`) that runs `psql` against `postgres` idempotently: it creates role `marquez` (password `marquez`) and database `marquez` owned by it, using `SELECT … WHERE NOT EXISTS … \gexec`. This works on an existing Postgres volume, so no reset is needed. Store the SQL in `stack/postgres-init/01-marquez.sql`. Record in plan.md "Implementation Notes" that this one-off service replaces the planned `docker-entrypoint-initdb.d` script (which runs only on an empty volume)
- [X] T012 In `stack/compose.yaml` add `marquez-api` (`marquezproject/marquez:0.50.0`; env `POSTGRES_HOST=postgres`, `POSTGRES_PORT=5432`, `POSTGRES_DB=marquez`, `POSTGRES_USER=marquez`, `POSTGRES_PASSWORD=marquez`, `MARQUEZ_PORT=5000`, `MARQUEZ_ADMIN_PORT=5001`, `JAVA_OPTS=-Xmx512m`; **no host port**; healthcheck `curl -f http://localhost:5001/healthcheck`; depends on `marquez-db-init` completed) and `marquez-web` (`marquezproject/marquez-web:0.50.0`; env `MARQUEZ_HOST=marquez-api`, `MARQUEZ_PORT=5000`, `WEB_PORT=3000`; port `${MARQUEZ_WEB_PORT:-3000}:3000`). Check the env var names against the 0.50.0 images' docs and fix them if they differ
- [X] T013 In `stack/compose.yaml` add `relatorio`: the stack image (`aurora-stack-airflow`, `pull_policy: never`), command `python -m http.server 8090 -d /opt/stack-data/elementary`, port `${REPORT_PORT:-8090}:8090`, volume `./data:/opt/stack-data:ro`. Create `/opt/stack-data/elementary` with a placeholder `index.html` (pt-BR: "relatório ainda não gerado — rode o DAG") in `airflow-init`
- [X] T014 In `stack/compose.yaml` `x-airflow-common.environment` add `AIRFLOW__OPENLINEAGE__NAMESPACE: aurora`, `AIRFLOW__OPENLINEAGE__TRANSPORT: '{"type":"http","url":"http://marquez-api:5000","endpoint":"api/v1/lineage","timeout":5}'` and `MARQUEZ_URL: http://marquez-api:5000`. Add `MARQUEZ_WEB_PORT=3000` and `REPORT_PORT=8090` to `stack/.env.example`
- [X] T015 Update `stack/Makefile`: `check` requires **≥ 10 GB** free RAM (pt-BR error: "a trilha stack (Fase 2) precisa de pelo menos 10 GB"); `up` prints 3 URLs (Airflow `:8080`, linhagem `:3000`, relatório `:8090`); `reset`'s message mentions the lineage history and the report
- [X] T016 Check the setup: `make reset && make up`. Every service is healthy, `http://localhost:3000` loads, `curl -sf http://marquez-api:5000/api/v1/namespaces` works from the scheduler container, and `http://localhost:8090` shows the placeholder. **If Marquez's migrations fail on Postgres 16**, apply the R5 fallback: a separate `marquez-db` service on `postgres:14` with its own `./data/marquez-postgres` volume. Record the outcome in plan.md "Implementation Notes"

**Checkpoint**: the stack runs, with the new services idle.

---

## Phase 3: Foundational (Blocking Prerequisites)

**Purpose**: the per-run breaker setting, the shared macros, the incident lifecycle on the stack, and the test
fixtures every story uses.

**⚠️ CRITICAL**: no user story can start until this phase is complete.

- [X] T017 [P] Write `stack/tests/test_incident_cli.py` (tests first): `incident list` shows an open incident after `ingest` with `incident=centavos`; `detect` sets `detected_at`; `resolve` restores Bronze (the redelivered batch is gone, the original batch is back) **and does not build any layer** (Silver is unchanged right after `resolve`); `reveal` returns the shared description
- [X] T018 Write `stack/agentready_stack/src/agentready_stack/incidents_cli.py` with `detect`, `resolve`, `reveal` and `list`, calling the shared `agentready.incidents` functions on the stack warehouse. `resolve` must **not** call `pipeline.run()`; print the TTD/TTR returned by `incidents.resolve()` in pt-BR. Wire it as `agentready-stack incident <action>` in `cli.py`
- [X] T019 Add `incidente` to `stack/Makefile`: `make incidente ACAO=detectar|resolver|revelar|listar` maps to `detect|resolve|reveal|list`; `resolver` then runs the same API call as `make run` with `ARGS='{}'` (research R8). pt-BR usage message when `ACAO` is missing
- [X] T020 [P] Write `stack/dbt/aurora/macros/observability_bands.sql`: `obs_band(kind)` returns `(lo, hi)` from `var('obs_bands')` (defaults from T010's values), `obs_min_history()` from `var('min_history', 7)`, and `breaker_on()`, which turns `var('block_on_distribution_anomaly', false)` into a SQL boolean whether it arrives as a bool or as the strings `'True'`/`'False'`/`'true'`/`'false'` (Cosmos renders XCom templates as strings)
- [X] T021 Add the DAG param `disjuntor_distribuicao` (`Param("compartilhado", enum=["compartilhado","ligado","desligado"], description="Disjuntor de distribuição só nesta execução (Bloco 5)")`) to `stack/dags/aurora_midia_diario.py`, and pass `--dag-run-id {{ run_id }}` to `task ingest` (contracts/dag-interface.md)
- [X] T022 In `stack/agentready_stack/src/agentready_stack/tasks.py` `ingest()`: resolve the breaker. `compartilhado` → `observability.block_on_distribution_anomaly` from the same shared `guardrails()` reader `pipeline.run()` uses; `ligado`/`desligado` → `true`/`false` with source `override`. Read `min_history` from `STACK_CONFIG`. Write a row into `ops.stack_run_settings` (`dag_run_id VARCHAR, block_on_distribution_anomaly BOOLEAN, source VARCHAR -- 'compartilhado' | 'override', min_history INTEGER, decided_at TIMESTAMP`), log `disjuntor de distribuição: ligado|desligado (configuração compartilhada|override desta execução)`, and add `"breaker": {"value": bool, "source": str}, "min_history": int` to the returned XCom. Reject unknown values with a pt-BR `ValueError`
- [X] T023 Extend `stack/tests/conftest.py`: (a) a dbt-build helper that takes `vars` (`reference_ts`, `block_on_distribution_anomaly`, `min_history`); (b) `run_incident(kind, breaker=False)`: generate → build → `incidents.inject(kind)` → build, on a temporary warehouse; (c) a `short_history` fixture that keeps only the last 3 days of Bronze conversions; (d) a `marquez` fixture that reads `MARQUEZ_URL` and **skips** with "Marquez indisponível: rode `make test-live`" if it's unreachable

**Checkpoint**: the breaker setting and incident lifecycle exist; the fixtures are ready.

---

## Phase 4: User Story 1 — The stack catches the `centavos` incident that passes the contract (Priority: P1) 🎯 MVP

**Goal**: distribution detection after Gold, plus the breaker inside the contract stage (FR-001–FR-008).

**Independent Test**: quickstart V-P2-1, V-P2-2, V-P2-4 and V-P2-5.

### Tests for User Story 1 (write first, confirm they fail)

- [X] T024 [P] [US1] Write `stack/tests/test_breaker.py`: `on_quarantines_and_bars` (`centavos` with the breaker on → `meta.batch_status` row `status='barred'`, `barred_by='distribuicao'`; rows in `quarantine.conversions` with reason exactly `anomalia de distribuição: ticket médio fora da banda`; **0** rows of that batch in `silver.conversions` and Gold); `off_reports_only` (breaker off → batch `passed`, rows in Silver); `override_is_per_run` (`ingest` with `ligado`, then `ingest` with no param → the second run's `ops.stack_run_settings` row is the shared value, `source='compartilhado'`); `contract_barred_not_requarantined` (`renomeacao` with the breaker on → the batch's `barred_by='contrato'`, and its quarantine reasons are the contract's, with no distribution reason); `breaker_model_error_stops_gold` (force a SQL error in `distribution_by_batch` with the test-only var `obs_force_error: true`; assert dbt reports the model as errored and `gold.campaign_daily` is unchanged from the previous build, FR-008(a)); `short_history_never_blocks` (with `short_history`, breaker on → nothing barred by distribution)
- [X] T025 [P] [US1] Write `stack/tests/test_observability.py`: `centavos_passes_contract_fails_distribution` (contract-stage batch `passed`; `meta.observability_checks` has `distribuição|conversions/ga4.order_value_brl` with `status='fail'` and a `detail` naming the `-redelivery` batch); `incident_pillar[kind]`, parametrized as centavos→`distribuição`, renomeacao→`esquema`, lote_duplicado→`volume`, feed_parado→`frescor` (that pillar has a `fail` for a ga4/conversions target); `clean_morning_matches_default` (the set of `(pillar, target, status != 'fail')` equals the default track's `observability.report()` on the same scenario and day); `short_history_warns` (volume and distribution are `warn` with `histórico insuficiente` in `detail`); `verdicts_match_schema` (every row validates against `specs/002-stack-lineage-observability/contracts/observability-check.schema.json`); `report_failure_is_warning` (the `relatorio` callable with a missing `edr` binary returns normally and logs `relatório de observabilidade não atualizado`)
- [X] T026 [P] [US1] Extend `stack/tests/test_dag_integrity.py`: tasks `observabilidade.verificar` (Cosmos group, models only), `observabilidade.testes`, `observabilidade.resumo` and `observabilidade.relatorio` exist; `gold` → `observabilidade.verificar` → `agente.executar` (the agent's upstream includes the obs model tasks, the FR-008 fail-safe); `testes`, `resumo` and `relatorio` are leaves with `retries=0`; `agente.executar` has no upstream test task from `observabilidade` (a failed verdict must not stop the agent, US1 AS2); param `disjuntor_distribuicao` has the 3 enum values; tags include `stack-fase-2` and `bloco-5` **Add new test functions only; don't modify existing ones** (FR-017).

### Implementation for User Story 1

- [X] T027 [US1] Write `stack/dbt/aurora/models/contrato/distribution_by_batch.sql` (schema `meta`, tag `contrato`). Columns: `source VARCHAR, batch_id VARCHAR, ingested_at TIMESTAMP -- max(ingested_at) of the batch, avg_ticket DOUBLE -- avg(order_value_brl), baseline DOUBLE -- median of avg_ticket over all of the source's batches (the batch itself included), ratio DOUBLE, history_points INTEGER -- number of batches for the source, out_of_band BOOLEAN -- ratio NOT BETWEEN lo AND hi and history_points >= min_history`. Input: rows of `contract_checked__conversions` with `len(violations)=0` from batches with `rate <= max_rate` only (no contract-barred batch), with `order_value_brl` cast as in Silver. Support the test-only var `obs_force_error` (default false; when true, select from a non-existent relation) for T024
- [X] T028 [US1] Change `stack/dbt/aurora/models/contrato/batch_status.sql`: add `barred_by VARCHAR` (`'contrato'` when `rate > max_rate`; else `'distribuicao'` when `{{ breaker_on() }}` and the batch is `out_of_band` in `distribution_by_batch`; else NULL). `status = 'barred'` when `barred_by` is not null. The contract reason wins
- [X] T029 [US1] Change `stack/dbt/aurora/models/contrato/quarantine__conversions.sql`: add (UNION ALL) the rows of distribution-barred batches with `violations = ['anomalia de distribuição: ticket médio fora da banda']`, using the same payload expression (`contract_param('conversions','quarantine_payload')`) and the same `schema_broken`/`keep_previous_if_broken` handling
- [X] T030 [US1] Change `stack/dbt/aurora/models/silver/conversions.sql` to also exclude batches with `barred_by = 'distribuicao'` (join `batch_status` or `distribution_by_batch` + `breaker_on()`), keeping the schema-break behavior
- [X] T031 [P] [US1] Write `stack/dbt/aurora/models/observabilidade/obs_frescor.sql`: one row per `gold.source_health` row, `pillar='frescor'`, `target=dataset||'/'||partition`, `status` `pass`/`fail` from `status='fresh'`, `observed=age_hours`, `baseline=sla_hours`, `detail='última carga ok há {age_hours}h (SLA {sla_hours:.0f}h)'` formatted exactly like `observability.freshness()`
- [X] T032 [P] [US1] Write `stack/dbt/aurora/models/observabilidade/obs_volume.sql` with the same SQL logic as `observability.volume()`: `bronze.conversions`, `current_date`, the previous 14 days, a median that excludes days with 0 rows, `target='conversions/'||source`, band from `obs_band('volume')`. `status='warn'` with `detail='histórico insuficiente ({n} de {min} dias necessários)'` when the days with data < `obs_min_history()`. Otherwise `detail` copies `ontem: {n} linhas recebidas vs mediana {baseline:.0f} ({ratio:.1f}x)`
- [X] T033 [P] [US1] Write `stack/dbt/aurora/models/observabilidade/obs_distribuicao.sql` with the same logic as `observability.distribution()`: on **post-breaker** `silver.conversions`, the per-batch average ticket vs the source median; report only the **latest batch per source** (by `max(ingested_at)`); `target='conversions/'||source||'.order_value_brl'`; band from `obs_band('distribution')`; `warn` on short history (batches < min); `detail` copies `ticket médio do último lote {batch_id}: R$ {avg:,.2f} vs mediana R$ {med:,.2f} ({ratio:.1f}x)`, matching Python's `,` thousands formatting
- [X] T034 [P] [US1] Write `stack/dbt/aurora/models/observabilidade/obs_esquema.sql` (or `.py` if string-building needs it) with the same logic as `observability.schema()`: per contract, compare `information_schema.columns` of the physical Bronze table with the contract's columns + `batch_id`, and flag required columns more than 50% NULL in the latest batch. Read the contract columns from `meta.contract_registry`. If the registry doesn't publish `physical`, `columns` and `required_columns` yet, add them in `stack/agentready_stack/src/agentready_stack/dbt_contracts.py` `registry_relation()`. `detail` copies `conforme contrato v{version}` or the joined `colunas inesperadas [...]`, `colunas ausentes [...]`, `{col} {pct} nulo no último lote` strings
- [X] T035 [US1] Write `stack/dbt/aurora/models/observabilidade/observability_checks.sql` (alias `observability_checks`, schema `meta`) as a UNION ALL of the four models plus `reference_ts = var('reference_ts')`. Columns: `pillar VARCHAR -- frescor | volume | distribuição | esquema, target VARCHAR, status VARCHAR -- pass | fail | warn, observed DOUBLE, baseline DOUBLE, ratio DOUBLE, detail VARCHAR, reference_ts TIMESTAMP`. In `dbt_project.yml` add folder `observabilidade` with `+tags: ["observabilidade"]`, `+schema: meta`
- [X] T036 [US1] Write `stack/dbt/aurora/tests/generic/observability_check_passes.sql` (fails on rows with `status='fail'`) and `stack/dbt/aurora/models/observabilidade/_observabilidade.yml`, which applies it to each `obs_*` model with `config: {severity: error}` and pt-BR descriptions per pillar. (A failed verdict must show as an error in the Elementary report, not a warning; our own `warn` is reserved for short history, research R7.)
- [X] T037 [US1] In `stack/scripts/contracts-sync.sh` (it runs at init and in `contratos.lint`), after the export, run once in the dbt venv: `dbt run --select elementary` (creates Elementary's tables) and the package's artifacts-upload operation (check the macro name in the installed 0.26.1 package, e.g. `elementary.upload_dbt_artifacts`), since autoupload is disabled (T008)
- [X] T038 [US1] Write `stack/agentready_stack/src/agentready_stack/observe.py`: `verdicts(con)` reads `meta.observability_checks`; `print_table()` prints the pt-BR table `pilar | alvo | ok | detalhe` (ok = `✅` pass, `⚠️` warn, `❌` fail), the same shape as `agentready observe`; `class ObservabilityAlert(RuntimeError)`. Add `observe()` to `tasks.py` (raise the alert if any verdict is `fail`; the last stdout line is the JSON verdict list) and `agentready-stack task observe` to `cli.py`
- [X] T039 [US1] Add `make observe` to `stack/Makefile` (runs `agentready-stack task observe` and doesn't treat exit 1 as an error, just prints)
- [X] T040 [US1] In `stack/dags/aurora_midia_diario.py` add `TaskGroup("observabilidade")`: `verificar = dbt_group("verificar", "observabilidade", {"reference_ts": <same XCom as gold>, "min_history": "{{ ti.xcom_pull(task_ids='ingestao.preparar')['min_history'] }}"}, test_behavior=TestBehavior.NONE)` (models only; extend `dbt_group()` with an optional `test_behavior` argument); `testes` = one `DbtTestLocalOperator` (`select=["tag:observabilidade"]`, same profile/execution config and vars, pool `duckdb_writer`, `retries=0`), a **leaf**, so Elementary records each verdict through its hook; `resumo` = `@task(pool=POOL, retries=0)` → `run_stack("task","observe")`; `relatorio` = `@task(pool=POOL, retries=0)` that runs `/opt/venvs/dbt/bin/edr report --file-path /opt/stack-data/elementary/index.html --project-dir $DBT_PROJECT_DIR --profiles-dir $DBT_PROJECT_DIR` and, on any failure, prints `relatório de observabilidade não atualizado: <erro>` and returns normally. Wire `gold >> verificar >> agente`, `verificar >> [testes, resumo]`, `testes >> relatorio` (the report includes this run's test results; `relatorio` uses `trigger_rule="all_done"`). Pass `{"block_on_distribution_anomaly": "{{ ti.xcom_pull(task_ids='ingestao.preparar')['breaker']['value'] }}", "min_history": …}` as vars to `contratos.verificar`. Change the tags to `stack-fase-2` and add `bloco-5`
- [X] T041 [US1] In `tasks.py` `quality_alert()`, include `barred_by` in the query and the pt-BR table, so a distribution-barred batch reads "barrado por anomalia de distribuição" and a contract-barred one reads as before
- [X] T042 [US1] Run `make test` until T024–T026 pass. Then validate on the live stack: quickstart V-P2-1, V-P2-2, V-P2-4, V-P2-5 (between incidents, use `make incidente ACAO=resolver`). Time a full run up to the approval pause. **If it's over 5 min (SC-007)**, apply the R6 fallback (Cosmos `TestBehavior.BUILD` in `dbt_group`) and re-measure. Record the findings in plan.md "Implementation Notes"

**Checkpoint**: Block 5's core lesson works on the stack. MVP.

---

## Phase 5: User Story 2 — Parity of observability verdicts with the default track (Priority: P2)

**Goal**: the parity check compares verdicts exactly (stack `warn` = default pass) across 7 scenarios
(FR-015, SC-003).

**Independent Test**: quickstart V-P2-6. `make parity SCENARIO=todos` → 0 differences.

- [X] T043 [P] [US2] Extend `stack/tests/test_parity.py`: the 4 new scenarios report 0 differences in `campaign_daily`, `source_health`, `decisions` **and** `observability`; `band_drift_is_reported` (stack built with `obs_bands.distribution=[0.9,1.1]` → at least one `observability` diff is listed, US2 AS3); `warn_maps_to_pass` (unit: a stack `warn` against a default `pass` is not a diff, but a stack `warn` against a default `fail` is); the JSON output validates against `specs/002-stack-lineage-observability/contracts/parity-report.schema.json` (2.0.0) **Add new test functions only; don't modify existing ones** (FR-017).
- [X] T044 [US2] First, run the 4 incident scenarios through the stack side alone. Expected data failures must not crash parity: if `dbt build` exits non-zero only because of `severity: error` tests (the obs tests from T036, or contract tests on an incident), have the stack's `_build` run `dbt run` then `dbt test`, treating test failures as data (logged, not raised) and model errors as crashes; add `test_parity::incident_build_does_not_crash`. Then: Extend `stack/agentready_stack/src/agentready_stack/parity.py`: `SCENARIOS += ("incidente_centavos","incidente_renomeacao","incidente_lote_duplicado","incidente_feed_parado")` (each: generate → build → `incidents.inject(kind)` → build, on both tracks, breaker from the shared file only); collect verdicts (default: `observability.report(con)` mapped `ok`→`pass`/`fail`; stack: `meta.observability_checks.status` with `warn`→`pass`); compare as `compared.observability` keyed `<pillar>|<target>`, field `status`; the stack's `_build` must also build tag `observabilidade` (a full `dbt build` already does). Bump the report `$id` to 2.0.0
- [X] T045 [US2] Update `stack/Makefile` `parity` help and `stack/agentready_stack/src/agentready_stack/cli.py` so `SCENARIO` accepts the 4 new names and `todos` runs all 7; the pt-BR summary table gets an "observabilidade" column
- [X] T046 [US2] Run `make parity SCENARIO=todos` on the live stack: 0 differences in 7 scenarios. Record the time in plan.md "Implementation Notes"

**Checkpoint**: on stage, "the conclusions didn't change" is proven, not just claimed.

---

## Phase 6: User Story 3 — Trace an incident's blast radius through pipeline-emitted lineage (Priority: P3)

**Goal**: every run sends OpenLineage events to Marquez, including the agent's datasets and trace id
(FR-009–FR-014).

**Independent Test**: quickstart V-P2-3 and V-P2-7 (outage).

- [X] T047 [P] [US3] Write `stack/tests/test_lineage.py` (needs the `marquez` fixture; runs under `make test-live` against the live stack after a `make run`): `graph_has_agent_with_trace` (Marquez job `aurora_midia_diario.agente.executar` in namespace `aurora` has inputs `gold.campaign_daily`, `gold.source_health`, `meta.batch_status` and outputs `ops.change_log`, `ops.approval_queue`, `ops.campaigns` in namespace `duckdb:///opt/stack-data/warehouse.duckdb`; its latest run has facet `agentready_trace.trace_id` equal to the run's `ops.agent_runs`/`change_log` trace id); `path_from_bronze_to_agent` (Marquez's lineage graph from `bronze.conversions` reaches the agent job); `every_task_has_an_event` (for the run's DAG run, every task instance in a terminal state has a COMPLETE or FAIL event in Marquez, all under the same parent run, per contracts/lineage-events.md guarantee 1); `rerun_adds_runs_only` (a second run adds runs, and the job count stays the same)
- [X] T048 [US3] Add `inlets`/`outlets` to the Python tasks in `stack/dags/aurora_midia_diario.py` per contracts/dag-interface.md → "Inlets / outlets", as Airflow `Asset`s with URI `duckdb:///opt/stack-data/warehouse.duckdb/<schema>.<table>` (`ingestao.preparar`, `observabilidade.resumo`, `agente.executar`, `aprovacao.aplicar`)
- [X] T049 [US3] Write `stack/dags/_lineage_facets.py` (the dags folder is on Airflow's import path; the Airflow env can't import `agentready_stack`): `trace_facet(task_instance, ti_state)` returns `{"agentready_trace": <RunFacet with trace_id>}` only for `task_id == "agente.executar"`, reading `trace_id` from that task's XCom, and `{}` otherwise. Set `AIRFLOW__OPENLINEAGE__CUSTOM_RUN_FACETS: _lineage_facets.trace_facet` in `stack/compose.yaml`. The facet shape follows contracts/lineage-events.md (`_producer: agentready-stack`, `_schemaURL: urn:agentready:facet:trace:1.0.0`). Record in plan.md that this lives in `dags/`, not in `agentready_stack.lineage` as originally planned
- [X] T050 [US3] Trigger a run and check Marquez (`curl` the job and lineage endpoints). **If the `duckdb://` Assets of T048 don't appear as datasets** (the provider has no converter for the scheme), apply the R4 fallback: add `openlineage-python==1.53.0` to `stack/requirements/agent.in` (recompile), write `stack/agentready_stack/src/agentready_stack/lineage.py` with `emit(job, inputs, outputs, facets)`, which sends START/COMPLETE to `MARQUEZ_URL` with a ParentRunFacet built from env `OL_PARENT_*` (timeout 5 s; never raises; logs `linhagem indisponível: …`), call it from `tasks.ingest/run_agent/apply_decision/observe`, and pass the parent ids from the DAG with the provider's `lineage_parent_id`/`lineage_run_id` macros. Record which path was used in plan.md "Implementation Notes"
- [X] T051 [US3] Add `lineage-check` to `stack/agentready_stack/src/agentready_stack/cli.py`: `GET {MARQUEZ_URL}/api/v1/namespaces/aurora` with a 5 s timeout; it always exits 0 and prints `linhagem indisponível: <motivo>` when it fails. Call it from `tasks.close_run()` and add the result to the summary line (FR-013)
- [X] T052 [US3] Add `decisions --since <iso> [--json]` to `incidents_cli.py`: a new query (not `observability.decisions_since`) over `ops.change_log` (executed) and `ops.approval_queue` (queued) since T, with `id, campaign_id, action, change, trace_id, ts, kind` and, per trace id, the Marquez UI link `http://localhost:${MARQUEZ_WEB_PORT}/lineage/job/aurora/aurora_midia_diario.agente.executar`. Add `make decisoes DESDE=<iso>` to `stack/Makefile` (FR-012)
- [X] T053 [US3] Add `make test-live` to `stack/Makefile`: it runs `test_lineage.py`, then `stack/scripts/lineage-outage-check.sh`, which records the task states and decisions of a run, `docker compose stop marquez-api`, triggers an identical run (`reset_scenario: true`), checks the same task states and decisions plus `linhagem indisponível` in the closing log, and then `docker compose start marquez-api` (FR-013, plan test `outage_same_states_and_decisions`)
- [ ] T054 [US3] Validate V-P2-3 (time bronze→agent in the UI, < 2 min, SC-005), V-P2-7 step 1, and US3 AS4 (`make down && make up` keeps history; `make reset` clears it). Record in plan.md "Implementation Notes"

**Checkpoint**: lineage comes from what ran, up to the agent's decision.

---

## Phase 7: User Story 4 — The guide explains what Phase 2 replaced and updates the gaps (Priority: P4)

**Goal**: README and instructor script (pt-BR) per FR-020–FR-023.

**Independent Test**: a reader finds a replaced module for every Phase 2 tool, the gaps match behavior, and the
Block 5 runbook works using only the guide (V-P2-8).

- [X] T055 [US4] Update `stack/README.md` (pt-BR): (a) the replacement map gains the plan.md "Replacement map additions" rows, including **partial** notes: Elementary runs our rules (median-ratio bands) and not its own anomaly statistics; Marquez doesn't show the semantic/MCP nodes; (b) "Lacunas conhecidas": remove the `centavos` and lineage/traces gaps that are now closed (keep traces as Phase 3); add Marquez "projeto ativo; última versão publicada 0.50.0 (out/2024)", the Postgres version Marquez documents (14) vs the one in use, the static lineage nodes left out, the short-history parity caveat (R7), and "o feed ga4 aparece na linhagem como `bronze.conversions` (sem nó por fonte até a Fase 4)"; (c) the roadmap marks Phase 2 as done; (d) prerequisites 10 GB, the three URLs, the new param `disjuntor_distribuicao` and the commands `observe`, `incidente`, `decisoes`, `test-live`
- [X] T056 [US4] Add a section "Bloco 5 na trilha stack" to `stack/README.md`: `make run ARGS='{"incident":"aleatorio"}'` → find the red `observabilidade.resumo` → open the report (`:8090`) → Marquez (`:3000`) from `bronze.conversions` to the agent ("o feed ga4 aparece na linhagem como `bronze.conversions`") → `make incidente ACAO=detectar` → `make decisoes DESDE=…` → `make rollback CHG=…` → `make incidente ACAO=resolver` (TTD/TTR) → post-mortem: `make run ARGS='{"incident":"centavos","disjuntor_distribuicao":"ligado"}'` shows the fix
- [X] T057 [P] [US4] Add a short pt-BR "Bloco 5 na trilha stack (opcional)" note to `docs/01-roteiro-do-instrutor.md` pointing to the README section and naming the one stage difference (the breaker as a per-run param instead of editing `config/guardrails.yaml`)
- [ ] T058 [US4] Dry run V-P2-8 with someone who hasn't seen the incident; record the time to identify the pillar and decisions (SC-006, target < 10 min) in `stack/README.md` → "Tempos medidos". If no participant is available, leave this task open and say so

**Checkpoint**: the study path and stage script are complete.

---

## Phase 8: Polish & Cross-Cutting Concerns

- [X] T059 [P] Extend `doctor` in `stack/agentready_stack/src/agentready_stack/cli.py`: print `elementary-data` (CLI) and the Elementary dbt package version, `apache-airflow-providers-openlineage`, and Marquez API health; fail (exit 2) only if DuckDB differs between the dbt and agent venvs, as before
- [X] T060 [P] Make sure `make test` runs every new non-live test file (`test_breaker.py`, `test_observability.py`, `test_incident_cli.py`, the extended `test_parity.py` and `test_dag_integrity.py`) and that `make help` lists `observe`, `incidente`, `decisoes` and `test-live` with pt-BR descriptions
- [ ] T061 Measure V-P2-9 on a clean checkout: `make up` time, the first run up to the approval pause (≤ 5 min), peak RAM from `docker stats` (confirm the 10 GB minimum or adjust `make check` and the README), and checkout → finished run (≤ 15 min, SC-007). Update "Tempos medidos" in `stack/README.md`
- [ ] T062 Final gates: `uv run pytest -q` at the repo root passes; `git diff main -- src/agentready` is empty (FR-018); `make test`, `make test-live` and `make parity SCENARIO=todos` pass on a clean clone. Record the results in plan.md "Implementation Notes"

---

## Dependencies & Execution Order

### Phase dependencies

- **Phase 1 (US5 upgrade)**: none. **Blocks everything** (gate T006).
- **Phase 2 (Setup)**: after T006.
- **Phase 3 (Foundational)**: after Phase 2. Blocks every story below.
- **US1 (Phase 4)**: after Phase 3. This is the MVP.
- **US2 (Phase 5)**: after US1. It compares the verdict table US1 builds.
- **US3 (Phase 6)**: after Phase 3. It's independent of US1/US2 for lineage itself, but T047's dataset list includes `meta.batch_status` (exists already). It can run in parallel with US1 if staffed. T052 needs T018.
- **US4 (Phase 7)**: after US1–US3, because it documents them.
- **Polish**: last.

### Within each story

Tests first (they must fail) → dbt models → stack Python → DAG wiring → live validation.
- US1: T027 → T028 → T029/T030; T031–T034 in parallel → T035 → T036; T038 → T039; T040 needs T035/T038; T042 last.
- US3: T048/T049 → T050 → T051–T053 → T054.

## Parallel Example: User Story 1

```text
Task: "T024 [US1] breaker tests in stack/tests/test_breaker.py"
Task: "T025 [US1] observability tests in stack/tests/test_observability.py"
Task: "T026 [US1] DAG integrity tests in stack/tests/test_dag_integrity.py"
# then, after T030:
Task: "T031 [US1] obs_frescor.sql"
Task: "T032 [US1] obs_volume.sql"
Task: "T033 [US1] obs_distribuicao.sql"
Task: "T034 [US1] obs_esquema.sql"
```

## Implementation Strategy

### MVP first (US5 gate → US1)

1. Phase 1 (upgrade) → **stop and validate** V-P2-0.
2. Setup → Foundational → US1.
3. **Stop and validate**: V-P2-1, V-P2-2, V-P2-4, V-P2-5. This alone closes the `centavos` gap on the stack.

### Incremental delivery

1. + US2 parity: proves the replacement didn't change any conclusion.
2. + US3 lineage: the triage's "what did it touch".
3. + US4 guide: the Block 5 runbook on the stack.
4. Polish: doctor, timing, clean-clone gates.

### Task counts

| Phase | Tasks |
|---|---|
| US5 upgrade (first) | 6 (T001–T006) |
| Setup | 10 (T007–T016) |
| Foundational | 7 (T017–T023) |
| US1 | 19 (T024–T042) |
| US2 | 4 (T043–T046) |
| US3 | 8 (T047–T054) |
| US4 | 4 (T055–T058) |
| Polish | 4 (T059–T062) |
| **Total** | **62** |
