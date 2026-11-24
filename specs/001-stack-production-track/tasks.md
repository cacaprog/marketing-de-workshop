---

description: "Task list for the Stack Track (Phase 1)"
---

# Tasks: Stack Track — Production-Shaped Version of the Workshop (Phase 1)

**Input**: Design documents from `/specs/001-stack-production-track/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md

**Tests**: REQUIRED. FR-021 and constitution Principle V ask for one automated test per Phase 1
promise. In each story, write the tests first and confirm they fail before implementing.

**Organization**: tasks are grouped by user story (spec.md priorities P1–P5).

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel (different files, no dependency on an unfinished task)
- **[Story]**: US1–US5 from spec.md
- All paths are relative to the repo root. Everything new lives under `stack/`.

## Global rules for every task (from the constitution and plan)

- Do **not** change the decision rules in `src/agentready/agent.py`, `capabilities.py` or
  `semantic.py` (Principle I). The only allowed edit to shared code is T047.
- Every text a user sees (logs, HITL forms, Makefile messages, README) is **pt-BR**. Code
  identifiers are English.
- Shared sources (`contracts/`, `config/`, `corpus/`, `src/agentready/`) are mounted read-only
  at `/opt/agentready`. Never copy them into `stack/`.
- Pin `duckdb==2.0.1` in every venv (research R3/R10).

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: the folder layout, the image and the services come up healthy, with nothing data-related yet.

- [X] T001 Create the `stack/` tree exactly as in plan.md "Source Code" (empty `__init__.py`/placeholder files where needed) and add `stack/data/`, `stack/config/passwords.json` and `stack/dbt/aurora/models/silver/_contracts.generated.yml` to `.gitignore`
- [X] T002 [P] Write `stack/requirements/dbt.in`, `stack/requirements/dcc.in` and `stack/requirements/agent.in`, and compile them with `uv pip compile` into `dbt.txt` (dbt-core 1.10.x, dbt-duckdb, pyyaml, duckdb==2.0.1), `dcc.txt` (datacontract-cli[duckdb] 1.0.x, duckdb==2.0.1) and `agent.txt` (the agentready runtime deps from the root `pyproject.toml` plus `anthropic`, duckdb==2.0.1); add a header comment to each `.in` explaining why the venv is isolated (research R10)
- [X] T003 [P] Write `stack/agentready_stack/pyproject.toml` (package `agentready_stack`, src layout, console script `agentready-stack = agentready_stack.cli:main`, depends on `agentready`) and empty modules `__init__.py` (must stay import-free, because the dbt venv has no Airflow/mcp/OpenTelemetry), `dbt_contracts.py`, `tasks.py`, `approvals.py`, `ledger.py`, `parity.py`, `cli.py` under `stack/agentready_stack/src/agentready_stack/`
- [X] T004 Write `stack/Dockerfile`: `FROM apache/airflow:3.3.2-python3.12`; add `astronomer-cosmos~=1.14` and `pytest` to the Airflow env; create `/opt/venvs/dbt`, `/opt/venvs/dcc` and `/opt/venvs/agent` with `uv venv` and `uv pip sync` from T002; in the agent venv install `/opt/agentready` (editable, `--no-deps`) plus `/opt/agentready/stack/agentready_stack`; in the dbt venv install `/opt/agentready` and `/opt/agentready/stack/agentready_stack`, both with `--no-deps` (dbt's Python models import `agentready_stack.dbt_contracts`, see T013); set `ENV AGENTREADY_HOME=/opt/agentready AGENTREADY_DB=/opt/stack-data/warehouse.duckdb AGENTREADY_TRACES=/opt/stack-data/traces`
- [X] T005 Write `stack/compose.yaml` based on the official Airflow 3.3 compose file, reduced to `postgres` (16, healthcheck), `airflow-init`, `airflow-apiserver` (port 8080), `airflow-scheduler` and `airflow-dag-processor`. Use LocalExecutor; set `TZ=${TZ:-America/Sao_Paulo}`; mount the repo root read-only at `/opt/agentready`, `./dags` at `/opt/airflow/dags`, `./dbt` at `/opt/airflow/dbt` and `./data` at `/opt/stack-data`; set `AIRFLOW__CORE__SIMPLE_AUTH_MANAGER_USERS=instrutor:admin,aprovadora:op` and `AIRFLOW__CORE__SIMPLE_AUTH_MANAGER_PASSWORDS_FILE=/opt/airflow/config/passwords.json`; the init step creates the pool `duckdb_writer` with 1 slot (research R1, R8, R11)
- [X] T006 [P] Write `stack/.env.example` (TZ, AIRFLOW_UID, AIRFLOW_PORT=8080), `stack/config/passwords.example.json` (`{"instrutor": "instrutor", "aprovadora": "aprovadora"}`) and `stack/config/stack.yaml` with `approvals: {response_timeout: "20h", approvers: ["aprovadora"]}` (20h, not 24h, so an unanswered request expires before the next 07:00 run; with `max_active_runs=1` a still-waiting run would otherwise delay the next day, see research R4), `schedule: "0 7 * * *"` and `alert: {new_only: true}`
- [X] T007 Write `stack/Makefile` targets `up`, `down`, `reset`, `logs`, with pt-BR messages per contracts/commands.md. `up` checks Docker Compose ≥ 2.14, ≥ 4 CPU and ≥ 8 GB free RAM, and fails with a clear pt-BR message if not; it then runs `docker compose up -d --wait` and prints the UI URL and users
- [X] T008 Check the setup: `cd stack && make up` brings every service to healthy, and the UI login works for `instrutor` and `aprovadora`; fix the image or compose file until it does

**Checkpoint**: an empty Airflow 3.3 runs locally with the three venvs in place.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: the dbt project and the data layers every story depends on, plus the test harness.

**⚠️ CRITICAL**: no user story can start until this phase is complete.

- [X] T009 Write `stack/dbt/aurora/dbt_project.yml` (profile `aurora`; folders `contrato/` and `silver/` tagged `contrato`, `gold/` tagged `gold`; materialized `table`) and `stack/dbt/aurora/profiles.yml` (dbt-duckdb, `path: "{{ env_var('AGENTREADY_DB') }}"`, threads 1)
- [X] T010 [P] Write `stack/dbt/aurora/macros/generate_schema_name.sql` so that `+schema: silver|quarantine|meta|gold` maps to exactly that schema with no target prefix
- [X] T011 [P] Write `stack/dbt/aurora/models/sources.yml` declaring `bronze.campaigns`, `bronze.ad_spend` and `bronze.conversions`
- [X] T012 Write `stack/dbt/aurora/models/contrato/contract_registry.py` (dbt-duckdb Python model, `schema: meta`, tag `contrato`): one row per contract from `agentready.contracts.load_all()` with columns `contract VARCHAR, contract_version VARCHAR, table_name VARCHAR, max_quarantine_rate DOUBLE, sla_hours DOUBLE (NULL if no latency SLA), partition_by VARCHAR (NULL if none), missing_columns VARCHAR[]` (from `contracts.missing_columns(session, c)`). This is the only source of contract parameters for the SQL models (research R5)
- [X] T013 Write the helper `checked_relation(dbt, session, name)` in `stack/agentready_stack/src/agentready_stack/dbt_contracts.py` (**not** under `stack/dbt/aurora/models/`: dbt treats every `.py` file there as a model, and Python models can't import neighbouring files). It may import only `agentready.contracts` and `duckdb`. It loads the contract with `agentready.contracts.load(name)`, builds `SELECT b.*, list_filter([<violation_exprs>], lambda x: x IS NOT NULL) AS violations FROM bronze.<t> b` and returns it as a DuckDB relation via `session.sql(...)`
- [X] T014 [P] Write `stack/dbt/aurora/models/contrato/contract_checked__campaigns.py`, `contract_checked__ad_spend.py` and `contract_checked__conversions.py`, each a `model(dbt, session)` that does `from agentready_stack.dbt_contracts import checked_relation` and returns `checked_relation(dbt, session, "<name>")` (`schema: meta`)
- [X] T015 Write `stack/dbt/aurora/models/contrato/batch_quarantine_rate.sql`: a union over the three checked models with `contract, batch_id, n, bad, rate = bad / n, limit` where `limit` comes from joining `{{ ref('contract_registry') }}` on `contract` (`max_quarantine_rate`); never hard-coded, never a dbt var
- [X] T016 [P] Write `stack/dbt/aurora/models/silver/{campaigns,ad_spend,conversions}.sql`: rows with `len(violations) = 0` **and** a batch rate ≤ limit, cast with the `contracts.CASTS` mapping (number→DOUBLE, integer→BIGINT, date→DATE, timestamp→TIMESTAMP; `ingested_at` is not cast), plus `batch_id`; `schema: silver`
- [X] T017 [P] Write `stack/dbt/aurora/models/contrato/quarantine__{campaigns,ad_spend,conversions}.sql` (`schema: quarantine`, alias without the prefix): `payload JSON, batch_id, ingested_at, violations VARCHAR[], quarantined_at`; rows of a blocked batch that had no violations get `['lote barrado pelo disjuntor: ' || round(rate*100,1) || '% de quarentena > ' || limit*100 || '%']`
- [X] T018 Write `stack/dbt/aurora/models/contrato/batch_status.sql` (`schema: meta`): `contract, contract_version, batch_id, ingested_at, rows, quarantined, rate, status` where `status ∈ {passed, barred}` (barred when rate > limit)
- [X] T019 [P] Write `stack/dbt/aurora/models/gold/dim_campaign.sql` and `campaign_daily.sql` with exactly the semantics of `pipeline.build_gold()`: conversions **aggregated before** the join; `COALESCE(orders|gross_revenue_brl|discount_brl, 0)`; one row per campaign per day
- [X] T020 [P] Write `stack/dbt/aurora/models/gold/source_health.py` (dbt-duckdb Python model, `schema: gold`, tag `gold`): call the shared `agentready.pipeline.freshness(session, now=datetime.fromisoformat(dbt.config.get("reference_ts")))` and return its rows with columns `dataset, partition, last_success_ingest, age_hours, sla_hours, status`; set `reference_ts` in `stack/dbt/aurora/models/gold/_gold.yml` as `config: {reference_ts: "{{ var('reference_ts') }}"}` for `source_health` (Python models can't call `var()`; they read it with `dbt.config.get("reference_ts")`), and call `dbt.ref()` on the three Silver models so dbt orders it after them. The freshness rule stays one shared function (parity); dbt owns materialization and dependencies
- [X] T021 Write `stack/tests/conftest.py`: create a temp dir, set `AGENTREADY_DB`/`AGENTREADY_TRACES`, and provide fixtures `scenario(now)` (calls `agentready.generate.generate(now)`), `dbt_build(select, vars)` (runs `dbtRunner` from the dbt venv in a subprocess against the temp DB) and `con`
- [X] T022 Add `test` to `stack/Makefile` as two runs that must both pass: (1) `docker compose run --rm airflow-scheduler /opt/venvs/agent/bin/pytest /opt/agentready/stack/tests -q --ignore=/opt/agentready/stack/tests/test_dag_integrity.py`; (2) `docker compose run --rm airflow-scheduler python -m pytest /opt/agentready/stack/tests/test_dag_integrity.py -q` (Airflow's own Python, which has Airflow and Cosmos)
- [X] T023 Write `stack/tests/test_layers_smoke.py`: after `scenario` and `dbt_build("tag:contrato tag:gold")`, the tables `silver.*`, `quarantine.*`, `meta.batch_status`, `gold.campaign_daily` and `gold.source_health` exist and aren't empty; then run it with `make test`

**Checkpoint**: `make test` passes the smoke test; dbt rebuilds every layer from Bronze.

---

## Phase 3: User Story 1 — Run the daily media pipeline end to end (Priority: P1) 🎯 MVP

**Goal**: one daily DAG runs ingest → contracts → Gold → agent → approvals → close, visibly and idempotently.

**Independent Test**: quickstart V1, V2 and V4: `make up`, `make run ARGS='{"reset_scenario": true}'`, every stage visible, the agent report in the logs, and a second run that skips the agent.

### Tests for User Story 1 ⚠️ write first

- [X] T024 [P] [US1] Write `stack/tests/test_dag_integrity.py`: `DagBag` imports `aurora_midia_diario` with no errors; groups run in the order `ingestao → contratos → gold → agente → aprovacao → fechamento`; `max_active_runs == 1`; every warehouse-writing task uses pool `duckdb_writer`; `catchup is False`; the params and defaults match contracts/dag-interface.md; `fechamento` runs when there are zero approval requests. Runs under Airflow's Python (see T022), so it must not import `agentready_stack`
- [X] T025 [P] [US1] Write `stack/tests/test_agent_stage.py::test_rerun_is_skipped_duplicate`: calling `tasks.run_agent()` twice on unchanged Gold gives `status="done"` and then `status="skipped_duplicate"`, and `ops.change_log` has 0 new rows on the second call; `test_changed_run_settings_are_not_duplicates` (after a `done` run, the same Gold with `autonomy_override=supervised` or `gullible=True` runs the agent again); `test_retry_after_partial_apply_does_not_reapply` (an `ops.agent_runs` row `running` with the same fingerprint plus one agent `ops.change_log` row after its `started_at` → `run_agent()` raises, the row becomes `failed_partial`, `ops.change_log` gets 0 new rows); `test_retry_after_clean_failure_reruns` (same `running` row with no changes → agent runs, status `done`)

### Implementation for User Story 1

- [X] T026 [US1] Implement `stack/agentready_stack/src/agentready_stack/ledger.py`: create `ops.agent_runs` with columns `run_id VARCHAR, dag_run_id VARCHAR, business_date DATE, input_fingerprint VARCHAR, status VARCHAR ∈ {running, done, skipped_duplicate, failed, failed_partial}, trace_id VARCHAR, started_at TIMESTAMP, finished_at TIMESTAMP, report JSON`; `fingerprint(con, brain, gullible)` = sha256 of the ordered rows of `gold.campaign_daily` and `gold.source_health`, `current_date`, `settings.model_version_info()`, the effective `ops.autonomy_override` (or `none`), `brain` and `gullible`; plus `already_done(fp)`, `prior_unfinished(fp)` (the latest row with this fingerprint whose status is `running` or `failed`, plus the `ops.change_log` rows with `actor` starting with `agent` and the `ops.approval_queue` rows with `requested_by='agent'` timestamped ≥ its `started_at`), `start(...)` and `finish(...)`
- [X] T027 [US1] Implement `tasks.ingest(params)` in `stack/agentready_stack/src/agentready_stack/tasks.py`: `reset_scenario` → `generate.generate()`; `backfill_meta` → `generate.backfill_meta(con)`; `incident` ≠ `nenhum` → `incidents.inject(con, kind or None for aleatorio)`; `autonomy_override` → `autonomy.set_override` (`limpar` → None, `manter` → no-op); log in pt-BR what was applied
- [X] T028 [US1] Implement `tasks.run_agent(brain, gullible, dag_run_id)` in `tasks.py`: if the fingerprint is already done, record `skipped_duplicate` and return; if `prior_unfinished(fp)` found changes or requests, mark that row `failed_partial`, log a pt-BR table of what was applied ("execução anterior aplicou N alteração(ões) e falhou; revise, use `rollback` se necessário e marque como resolvida") and raise `AirflowFailException` without running the agent; if it found none, mark it `failed` and continue; otherwise run `ReadyAgent(brain, gullible).run(con)`, print each step in pt-BR (kind + text) to the task log, collect the `ops.approval_queue` rows with `status='pending'` created by this run's `trace_id`, and return the XCom shape from contracts/dag-interface.md (`requests[]` with `request_id, action, campaign_id, current, proposed, justification, checks, autonomy_reasons`)
- [X] T029 [US1] Implement a first version of `approvals.py`: `to_hitl_kwargs(request) -> {"subject", "body"}`, rendering the pt-BR Markdown body from contracts/approval-request.md, and `apply(request_id, payload)` covering approve and reject through `capabilities.decide_approval` (expiry comes in US4)
- [X] T030 [US1] Implement `tasks.close_run(dag_run_id)` in `tasks.py`: upsert `ops.stack_watermark (last_success_ingest_max TIMESTAMP, dag_run_id VARCHAR, updated_at TIMESTAMP)` with `max(ingested_at)` across `silver.*`, and return a pt-BR summary
- [X] T031 [US1] Write `stack/dags/aurora_midia_diario.py` per contracts/dag-interface.md: schedule from `stack.yaml`, the params table, groups `ingestao` (`@task.external_python(python="/opt/venvs/agent/bin/python")` → `tasks.ingest`), `contratos` (Cosmos `DbtTaskGroup`, `select=["tag:contrato"]`, `ExecutionMode.LOCAL`, `dbt_executable_path=/opt/venvs/dbt/bin/dbt`, `LoadMode.DBT_LS`), `gold` (`DbtTaskGroup`, `tag:gold`, `vars={"reference_ts": "{{ dag_run.start_date.in_timezone(dag.timezone).naive() }}"}` or equivalent local naive timestamp), `agente` (→ `tasks.run_agent`), `aprovacao` (`HITLOperator.partial(options=["Aprovar","Rejeitar"]).expand_kwargs(...)` from the agent's `requests` plus a mapped `apply` task with `trigger_rule="all_done"`), `fechamento` (→ `tasks.close_run`, upstream = `agente` and the mapped `apply`, `trigger_rule="none_failed"` so it also runs when zero approvals were mapped); pool `duckdb_writer` on every writing task; `retries=1` except the HITL tasks
- [X] T032 [US1] Add `run` and `approvals` to `stack/Makefile`: `run` posts to `/api/v2/dags/aurora_midia_diario/dagRuns` with `conf=$(ARGS)` using the `instrutor` user; `approvals` lists pending HITL details through the REST API in a pt-BR table
- [X] T033 [US1] Validate quickstart V1, V2 and V4 against the running stack and fix any differences

**Checkpoint**: MVP. The stack runs the whole day end to end in the orchestrator, with no double-apply.

---

## Phase 4: User Story 2 — Prove the agent is unchanged: parity (Priority: P2)

**Goal**: one command shows the business tables, source health and agent decisions are identical on both tracks.

**Independent Test**: quickstart V5: `make parity SCENARIO=todos` → 0 differences in all three scenarios, exit code 0.

### Tests for User Story 2 ⚠️ write first

- [X] T034 [P] [US2] Write `stack/tests/test_parity.py`: for each of `manha`, `pos_backfill` and `supervisionado`, `parity.run(scenario, reference_ts=<fixed>)` returns `ok=True`, and the JSON validates against `specs/001-stack-production-track/contracts/parity-report.schema.json`; plus a negative test that changes one `gold.campaign_daily.spend_brl` on the stack side and expects `ok=False` with that key and field in `diffs`

### Implementation for User Story 2

- [X] T035 [US2] Implement `stack/agentready_stack/src/agentready_stack/parity.py`: for a scenario and `reference_ts`, (a) default track: temp DB A → `generate.generate(now=ref)` → `pipeline.run(now=ref)`; (b) stack track: temp DB B → `generate.generate(now=ref)` → dbt build `tag:contrato tag:gold` with `vars={reference_ts: ref}`; scenario steps: `pos_backfill` runs `backfill_meta` and then rebuilds on both, `supervisionado` sets the override `supervised` on both; then run `ReadyAgent("rules").run(con)` on A and then on B in the same process (switching `AGENTREADY_DB` and reloading `agentready.settings`/`db` safely, or running each side in a subprocess and returning JSON)
- [X] T036 [US2] In `parity.py`, normalize and compare: `campaign_daily` keyed by `campaign_id|day` (numbers rounded to 2 decimals), `source_health` keyed by `dataset|partition` (`status`, `age_hours`, `sla_hours`), and decisions as `(campaign_id, action, status, new_daily_budget_brl, failed_check_ids)` with no IDs or timestamps; build the report per data-model.md
- [X] T037 [US2] Implement `stack/agentready_stack/src/agentready_stack/cli.py` `parity` (`--scenario manha|pos_backfill|supervisionado|todos`, `--reference-ts`, `--json`): print a pt-BR Rich table per scenario ("0 diferenças" or a list of diffs); exit codes `0` ok, `1` diffs, `2` environment error (e.g., a DuckDB lock, with a pt-BR message)
- [X] T038 [US2] Add `parity` to `stack/Makefile` (`docker compose run --rm airflow-scheduler /opt/venvs/agent/bin/agentready-stack parity --scenario $(SCENARIO)`, default `todos`) and validate quickstart V5

**Checkpoint**: parity proves on stage that only the infrastructure changed.

---

## Phase 5: User Story 3 — Contracts and circuit breaker stop bad data (Priority: P3)

**Goal**: Block 1 behaviors on production tools, plus contract lint and Silver assertions, plus "needs attention" only for new issues.

**Independent Test**: quickstart V2 (contract part), V6 and V7, plus `make test` for the contract stage tests.

### Tests for User Story 3 ⚠️ write first

- [X] T039 [P] [US3] Write `stack/tests/test_contract_stage.py`: `test_quarantines_rows_with_reasons` (dirty conversions such as a negative value, a comma decimal and `C99` are in `quarantine.conversions` with matching reasons and not in Silver); `test_bars_batch_over_limit` (the ga4 batch from day 20 has `status='barred'` and 0 of its rows are in `silver.conversions`); `test_duplicate_retry_batch_quarantined` (the `-retry` rows are quarantined as `duplicado`); `test_schema_break_keeps_last_good` (rename `bronze.conversions.campaign_id`, rebuild, `silver.conversions` is unchanged and every batch is `barred` with `rate=1.0`)
- [X] T040 [P] [US3] Write `stack/tests/test_gold_and_health.py`: `test_no_fan_out` (sum of `gold.campaign_daily.spend_brl` = sum of `silver.ad_spend.spend_brl`); `test_freshness_per_feed` (`conversions/meta_capi` is `stale`, `conversions/ga4` is `fresh`); `test_stale_feed_yields_null_metrics` (`semantic.query` for C03/C04 returns NULL ROAS, not 0); and in `stack/tests/test_agent_stage.py` add `test_no_action_on_stale` and `test_gullible_injection_blocked` (mirroring the default `tests/test_workshop.py` assertions)

### Implementation for User Story 3

- [X] T041 [US3] Implement the schema-violation path per research R6: (a) in `agentready_stack/dbt_contracts.py` (`checked_relation`, reading `dbt.ref('contract_registry')`), when `missing_columns` isn't empty for the contract, emit `batch_id, ingested_at`, the contract columns as typed NULLs and `violations=['esquema: colunas ausentes: <cols>']`, so every batch gets `rate = 1.0` and is `barred` with `rows = quarantined = COUNT(*)` (matching `contracts._record_batches(schema_break=True)`; `batch_status.sql` needs no special case); (b) in `silver/{t}.sql` and `contrato/quarantine__{t}.sql`, add `UNION ALL SELECT * FROM {{ this }} WHERE (SELECT len(missing_columns) > 0 FROM {{ ref('contract_registry') }} WHERE contract = '<t>')`, guarded by `adapter.get_relation(this.database, this.schema, this.identifier)` so it is skipped on the first build, and exclude the new rows from quarantine when the contract is broken, so both tables keep their previous contents
- [X] T042 [US3] Add `contratos.lint` to the DAG in `stack/dags/aurora_midia_diario.py`: a `BashOperator` running `/opt/venvs/dcc/bin/datacontract lint` for each `/opt/agentready/contracts/*.odcs.yaml`, upstream of the dbt contract group; a failure stops the run
- [X] T043 [US3] Add `contracts-sync` to `stack/Makefile`: run `datacontract export dbt-models` for each `/opt/agentready/contracts/*.odcs.yaml` and write `stack/dbt/aurora/models/silver/_contracts.generated.yml`, mapping each contract's schema to the Silver models (`campaigns`, `ad_spend`, `conversions`). The file is generated and **never committed** (gitignored in T001; constitution: shared sources are referenced, not copied). Run the same step (a) in `airflow-init` in `stack/compose.yaml`, before the dag-processor starts, so Cosmos sees the tests when it parses the DAG, (b) in `contratos.lint` right after lint (T042), and (c) in the `stack/tests/conftest.py` session setup
- [X] T044 [US3] Implement `tasks.quality_alert()` in `tasks.py` and wire it as a leaf task `contratos.alerta_qualidade` in the DAG: read `meta.batch_status` rows with `status='barred'` and `ingested_at > ops.stack_watermark.last_success_ingest_max` (or every row if there's no watermark); if any exist, log a pt-BR table (contract, batch, rate, limit) and raise `AirflowFailException`; otherwise succeed
- [X] T045 [US3] Validate quickstart V2 (contract checks), V6 and V7: the first run's alert is red and a second run's is green; the centavos incident passes the contracts (the documented gap)

**Checkpoint**: bad data never reaches the agent, and only new problems turn the run red.

---

## Phase 6: User Story 4 — A human approves or rejects inside the orchestrator (Priority: P4)

**Goal**: full approval behavior: assigned approver, timeout fails safe as `expired`, decisions recorded with identity, live re-check.

**Independent Test**: quickstart V3 with `autonomy_override=supervised` (approve one, reject one, let one expire).

### Tests for User Story 4 ⚠️ write first

- [X] T046 [P] [US4] Write `stack/tests/test_approvals.py`: `test_approve_executes_and_logs_approver` (payload `chosen_options=["Aprovar"], responded_by_user={"id":"aprovadora",...}` gives outcome `executed`, `ops.change_log.actor='agent+aprovadora'`, queue `approved`); `test_reject_changes_nothing`; `test_timeout_is_expired` (payload with an empty `responded_by_user` and `chosen_options=["Rejeitar"]` gives outcome `expired`, `decided_by='sistema:timeout'`, `ops.campaigns` unchanged); `test_failed_hitl_task_is_expired`; `test_approved_but_state_changed_is_rejected_live_recheck` (lock the campaign before applying); `test_request_leaves_pending_once` (applying twice is a no-op the second time)

### Implementation for User Story 4

- [X] T047 [US4] Add `expire_approval(con, request_id: str, reason: str) -> str` to `src/agentready/capabilities.py` (additive; the only edit to shared code): `UPDATE ops.approval_queue SET status='expired', decided_by='sistema:timeout', decided_at=now() WHERE request_id=? AND status='pending'` inside a `tracing.span("human.approval_expired", ...)`; return a pt-BR message. Check that the default track's `uv run pytest -q` still passes unchanged
- [X] T048 [US4] Complete `stack/agentready_stack/src/agentready_stack/approvals.py`: `outcome(payload, ti_state, timeout_datetime)` returns `executed | rejected | expired | rejected_live_recheck` per the table in contracts/approval-request.md (expired when `responded_by_user` is empty or missing, or `responded_at ≥ timeout_datetime`, or the HITL task failed); `apply()` is idempotent (no-op if the request isn't `pending`) and records the optional `comentario` from `params_input` in the queue's `reason` suffix
- [X] T049 [US4] Update the `aprovacao` group in `stack/dags/aurora_midia_diario.py`: `defaults=["Rejeitar"]`, `response_timeout` parsed from `stack.yaml → approvals.response_timeout`, `assigned_users=[{"id": u, "name": u} for u in approvers]`, `params={"comentario": Param("", type="string")}`, `retries=0`; the `apply` mapped task reads the HITL task state and payload via XCom and the TI and calls `approvals.apply`
- [X] T050 [US4] Validate quickstart V3 (set `response_timeout: "2m"` temporarily), including `agentready rollback <CHG>` against the stack warehouse with `AGENTREADY_DB` set, and restore `20h`. Also: (a) confirm the `assigned_users` entry shape against the installed provider (log in as `instrutor`: the request must not be answerable; as `aprovadora`: it must be) and fix T049 if the user ID format differs; (b) time how long `aprovadora` takes to find, review and decide one request from the HITL inbox and record it next to the T057 timings (SC-006: under 1 minute)

**Checkpoint**: approvals happen where operators work, identity is recorded, and timeouts fail safe.

---

## Phase 7: User Story 5 — Understand what each tool replaces and what comes next (Priority: P5)

**Goal**: a pt-BR guide that turns the stack into a study path.

**Independent Test**: someone new can start the stack from `stack/README.md` alone and name, for each tool, the module it replaces.

- [X] T051 [US5] Write `stack/README.md` (pt-BR): what the stack track is and isn't; prerequisites and minimum resources; `make up/run/approvals/parity/test/down/reset`; users and the "local study only" warning; a pipeline diagram (ASCII, matching the root README style)
- [X] T052 [US5] Add the **mapa de substituição** to `stack/README.md`: tool → default-track module → block, copied from the plan.md replacement map, including the honest note that datacontract-cli is a partial replacement and `contracts.violation_exprs()` stays shared, and that Postgres is Airflow's own infrastructure
- [X] T053 [US5] Add the **roadmap** to `stack/README.md` for Phases 2–5 per spec FR-025 (tool, module replaced, block, scenario made more realistic), the **lacunas conhecidas** section (centavos passes the contracts until Phase 2), and the FR-026 rule ("ferramenta sem módulo substituído não entra")
- [X] T054 [P] [US5] Add a short "Trilha stack (opcional)" section to the root `README.md` linking to `stack/README.md`, stating it isn't needed for the workshop demo

**Checkpoint**: the stack is a study path, not just a list of tools.

---

## Phase 8: Polish & Cross-Cutting Concerns

- [X] T055 [P] Implement `agentready-stack doctor` in `stack/agentready_stack/src/agentready_stack/cli.py`: print the versions of duckdb in each venv, dbt-core, dbt-duckdb, cosmos, airflow and datacontract-cli; exit 1 if the duckdb versions differ; call it at the end of `make up`
- [X] T056 [P] Add a pt-BR error message for a DuckDB lock conflict (another process has the warehouse open) in `stack/agentready_stack/src/agentready_stack/tasks.py` and `parity.py` (exit code 2, per contracts/commands.md)
- [ ] T057 Run the whole of quickstart.md (V1–V9) on a clean checkout and note the elapsed time against SC-001 (≤ 15 min, image downloads excluded) the run duration (≤ 5 min) and the approval decision time from T050 (SC-006, < 1 min) in `stack/README.md`
- [ ] T058 Run the default suite `uv run pytest -q` at the repo root and `make test` in `stack/`; both must pass (SC-003, SC-004); confirm `git status` shows changes only under `stack/`, in `src/agentready/capabilities.py` (T047), `README.md` (T054), `.gitignore` (T001), and the approved ODCS 3.1 migration (`contracts/*.odcs.yaml`, `src/agentready/contracts.py`, `docs/00-*.md`, `docs/01-*.md`)
- [ ] T059 [P] Run `/speckit-analyze` to check consistency between spec.md, plan.md and tasks.md, and record any accepted deviations in the plan's Complexity Tracking table

---

## Dependencies & Execution Order

### Phase dependencies

- **Setup (T001–T008)** → **Foundational (T009–T023)** → user stories.
- **US1 (P1)** depends on Foundational only. It's the MVP.
- **US2 (P2)** depends on Foundational and on `tasks.run_agent` (T028) being importable; it doesn't need the DAG.
- **US3 (P3)** depends on Foundational; T042/T044 edit the DAG from T031, so do them after US1.
- **US4 (P4)** depends on US1 (T029/T031 create the approval group it completes).
- **US5 (P5)** can start any time after the plan; T052/T053 should be finished after US3/US4 so the guide matches what was built.
- **Polish** comes last.

### Within each story

Tests first, and they must fail → helpers/package code → DAG wiring → Makefile → quickstart validation.

### Story dependency graph

```
Setup ─▶ Foundational ─┬─▶ US1 (MVP) ─┬─▶ US3 (DAG parts) ─┐
                       │              └─▶ US4 ─────────────┤
                       ├─▶ US2 (parity) ───────────────────┼─▶ US5 (final docs) ─▶ Polish
                       └─▶ US3 (dbt + tests parts) ────────┘
```

## Parallel Opportunities

- **Setup**: T002, T003 and T006 together; T004/T005 after T002.
- **Foundational**: T010, T011 together; T014, T016, T017 together after T013; T019, T020 together.
- **US1**: T024 and T025 (tests) together; T026 and T029 together.
- **US2 and US3** can proceed in parallel after Foundational (different files: `parity.py` vs dbt models and `test_contract_stage.py`).
- **US3**: T039 and T040 together.
- **US5**: T051–T054 can be drafted while US3/US4 are in progress.

### Example: launching the US3 tests together

```text
Task: "T039 [US3] contract stage tests in stack/tests/test_contract_stage.py"
Task: "T040 [US3] gold/health tests in stack/tests/test_gold_and_health.py"
```

## Implementation Strategy

### MVP first (US1)

1. Setup → Foundational → US1.
2. **Stop and validate**: quickstart V1, V2, V4. This alone already shows "the same day, run by Airflow + dbt".

### Incremental delivery

1. + US2 parity: the strongest message for the workshop ("the agent didn't change").
2. + US3 contract hardening: the Block 1 lesson on production tools.
3. + US4 approvals: the Block 4 lesson in the orchestrator UI.
4. + US5 guide: the study path and roadmap.
5. Polish: doctor, lock messages, timing, the full quickstart.

### Task counts

| Phase | Tasks |
|---|---|
| Setup | 8 (T001–T008) |
| Foundational | 15 (T009–T023) |
| US1 | 10 (T024–T033) |
| US2 | 5 (T034–T038) |
| US3 | 7 (T039–T045) |
| US4 | 5 (T046–T050) |
| US5 | 4 (T051–T054) |
| Polish | 5 (T055–T059) |
| **Total** | **59** |
