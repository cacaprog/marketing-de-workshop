---

description: "Task list for Stack Track Phase 4 (live ingestion, policy as code, snapshots)"
---

# Tasks: Stack Track Phase 4 — Live Ingestion, Policy as Code and Snapshots

**Input**: Design documents from `/specs/004-stack-ingestion-policy-snapshots/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md

**Tests**: REQUIRED. FR-021 and constitution Principle V ask for one automated test per Phase 4 promise (plan.md →
"Test matrix"). In each story, write the tests first and confirm they fail before implementing.

**Organization**: tasks are grouped by user story (spec.md US1–US4). Phase 1 ends with a **spike gate**: eight
facts the plan leaves open (quickstart V-P4-0) must be settled before any task code is written. Phase 2 moves the
data layers into the lake while Bronze is still filled from the shared generator (a "bridge"). Every Phase 1–3 test
and parity check must still pass at that checkpoint.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel (different files, no dependency on an unfinished task)
- **[Story]**: US1–US4 from spec.md
- All paths are relative to the repo root.

## Global rules for every task (from the constitution and plan)

- **Shared code (`src/agentready/`)**: only three files may change.
  - `policy.py` (new);
  - `capabilities.py` (the checks delegate to `policy.evaluate`);
  - `generate.py` (`create_ops_tables(con)` and `seed_live_state(con, now)` extracted, **no behavior change**).

  `agent.py`, `incidents.py`, `db.py`, `tracing.py`, `autonomy.py` and `settings.py` must not change. If a task
  seems to need one of them, stop and ask.
- **The default suite (`tests/`) is never edited.** New test files are allowed. `uv run pytest -q` must pass after
  every shared edit.
- **The stack never calls `agentready.db.connect()`.** It uses `agentready_stack.warehouse.connect()` (lake attached,
  `USE warehouse`) so the lake never gets an `ops` schema (research R2).
- **A restore never touches `ops`.** The restore list is the data-layer schemas only: `bronze_raw`, `quarantine`,
  `silver`, `gold`, `meta`, `elementary` and `bronze`.
- **Ingestion never repairs business data**: no dedupe, cast, rename, trim or fill. `ingested_at` is the source's
  delivery time, never the load time (contracts/ingestion.md → "Must never").
- **Unknown is NULL, never 0** (Principle III). For example, `ops.ingestion_loads.linhas` is "NULL when not
  `carregado`". Span attributes with unknown values are omitted.
- Every text a user sees (logs, Makefile messages, API error bodies, README, policy CLI) is **pt-BR**.
- **Pins**: DuckDB `2.0.1` (unchanged, every venv that opens the lake); the `ducklake` and `postgres` extensions
  preinstalled at build; OPA and dlt versions as recorded by T008.
- **Never answer HITL approvals for the user.** Live runs use `autonomy_override: "shadow"`, except where a task
  explicitly needs a pending request. There, stop and ask the user to approve as `aprovadora`.

---

## Phase 1: Setup and Spike Gate (Shared Infrastructure) 🚧

**Purpose**: add the new services, venv and extensions as configuration only, then settle the open facts.

- [X] T001 [P] Create `stack/postgres-init/03-ducklake.sql`: idempotent `CREATE ROLE ducklake LOGIN PASSWORD 'ducklake'` and `CREATE DATABASE ducklake OWNER ducklake`, guarded exactly like `stack/postgres-init/02-phoenix.sql`. Header comment in pt-BR: "Fase 4 — catálogo do DuckLake (metadados das camadas de dados); só estudo local"
- [X] T002 [P] Create `stack/requirements/ingest.in` with pt-BR comments ("Venv da ingestão (Fase 4): dlt isolado do agente e do Airflow"): `dlt[parquet]==1.32.0` (pinned by T008: dlt's `ducklake` extra requires `duckdb<2`), `duckdb==2.0.1`, `pyyaml>=6.0`, `pytest>=8`, `opentelemetry-sdk==1.45.2` and `opentelemetry-exporter-otlp-proto-http==1.45.2` (same pins as `agent.txt`, because `agentready_stack.telemetry` and the shared `tracing` import them), and `jsonschema>=4.0` if `agentready_stack` imports it at module level. Compile it to `stack/requirements/ingest.txt` with `uv pip compile --python-version 3.12 stack/requirements/ingest.in -o stack/requirements/ingest.txt`, and confirm `duckdb==2.0.1` survives resolution (if dlt caps duckdb below 2.0, record it for T008 → fallback R5)
- [X] T003 [P] In `stack/requirements/agent.in`, add `fastapi` (comment: "Fase 4: fontes simuladas (upstream); uvicorn e starlette já vêm com o mcp"). Recompile `stack/requirements/agent.txt` and confirm `duckdb==2.0.1` and the OpenTelemetry pins are unchanged
- [X] T004 In `stack/Dockerfile`:
  - (a) add `ingest` to the venv loop (`for v in dbt dcc agent ingest`);
  - (b) install the repo and `agentready_stack` editable with `--no-deps` into `/opt/venvs/ingest`, like the dbt venv;
  - (c) as root, `mkdir -p /opt/duckdb-extensions && chown airflow:`. Then, as airflow, run
    `/opt/venvs/agent/bin/python -c "import duckdb; c=duckdb.connect(); c.execute(\"SET extension_directory='/opt/duckdb-extensions'\"); c.execute('INSTALL ducklake'); c.execute('INSTALL postgres')"`
    (pt-BR comment: "extensões baixadas no build: a trilha roda offline");
  - (d) in `ENV`, set `AGENTREADY_DB=/opt/stack-data/ops.duckdb` (was `warehouse.duckdb`), and add
    `STACK_LAKE_DATA=/opt/stack-data/lake/`, `STACK_DUCKDB_EXTENSIONS=/opt/duckdb-extensions`;
  - (e) `mkdir -p /opt/stack-data/lake /opt/stack-data/upstream` in the same RUN that creates `/opt/stack-data`.
- [X] T005 In `stack/compose.yaml`:
  - (a) in `x-airflow-common.environment`, add **every variable** of the Phase 4 block in contracts/dag-interface.md →
    "Environment", with pt-BR comments (the block is the single source of truth). Example comment:
    "dlt: telemetria anônima desligada (FR-020)". Leave
    `AGENTREADY_POLICY_EVALUATOR` **commented out** until T062;
  - (b) add the `upstream` service: image `aurora-stack-airflow:fase1`, `user: "${AIRFLOW_UID:-50000}:0"`,
    entrypoint `/opt/venvs/agent/bin/python -m agentready_stack.upstream_app` (one process serving the public app on 8000 and the admin app on 8001, contracts/upstream-api.md),
    env `AGENTREADY_HOME=/opt/agentready`, `AGENTREADY_DB=/opt/stack-data/upstream/fontes.duckdb`, the repo
    read-only mount and `./data/upstream:/opt/stack-data/upstream`, ports `"127.0.0.1:${UPSTREAM_PORT:-8000}:8000"` only (**8001 is never published**; FR-020), a
    healthcheck GET `http://localhost:8001/admin/saude`, `restart: unless-stopped`, depends on `airflow-init` completed;
  - (c) add the `opa` service: image `openpolicyagent/opa:<version>-static` (version from T008), command
    `run --server --disable-telemetry --addr :8181 /policy guardrails:/config/guardrails.yaml` (exact data-prefix
    syntax confirmed by T008), volumes `./policy:/policy:ro` and `../config:/config:ro`, **no `ports:`**,
    healthcheck `opa` CLI or `/health` if the image has a probe tool (otherwise documented in a comment),
    `restart: unless-stopped`;
  - (d) in `airflow-init`'s command, `mkdir -p /opt/stack-data/lake /opt/stack-data/upstream`.
- [X] T006 [P] Add `UPSTREAM_PORT=8000` to `stack/.env.example` next to the other ports, with a pt-BR comment ("Fase 4: fontes simuladas — /docs mostra as APIs")
- [X] T007 In `stack/Makefile`:
  - (a) banner line in `up`: `Fontes simuladas (APIs) ....... http://localhost:$(UPSTREAM_PORT)/docs`, with `UPSTREAM_PORT ?= 8000`;
  - (b) `mkdir -p data/lake data/upstream` in `up` before compose;
  - (c) `reset`: also remove `data/lake`, `data/upstream`, `data/ops.duckdb` (and the old `data/warehouse.duckdb` if
    present), plus the `ducklake` database (it lives in the Postgres volume, which `reset` already deletes; state
    that in the message). The help text lists "camadas do lake (DuckLake) e as fontes simuladas".
- [X] T008 **Spike gate (V-P4-0)**: in a scratch script, `stack/scripts/spike_fase4.py` (deleted or kept as a dev tool, your call, documented), confirm the eight facts and record each one in `specs/004-stack-ingestion-policy-snapshots/plan.md` → a new "Implementation Notes" section, with the fallback taken if any:
  1. With `ops.duckdb` as the main DB, the lake attached as `warehouse` and `USE warehouse`, `SELECT * FROM ops.campaigns`,
     `CREATE TABLE IF NOT EXISTS ops.autonomy_override (level VARCHAR)` and `gold.x` resolve as research R2 says.
     Test it in dbt-duckdb with `database: warehouse` too.
  2. Pin the newest dlt 1.x that installs with `duckdb==2.0.1`. Check that its `ducklake` destination writes to the
     Postgres catalog + `data_path`, and that `timezone: false` gives a naive `TIMESTAMP` `ingested_at`. Fallback:
     dlt's `duckdb` destination with a pre-attached lake connection.
  3. With a fresh `pipelines_dir`, dlt restores schema and state from `bronze_raw._dlt_*`.
  4. `dbt build` (Python models included) and `edr report` work with the lake as the target. Fallback: Elementary in
     `ops`.
  5. OPA loads `config/guardrails.yaml` under `data.guardrails`. Pin the image version (v1.21.0 is the newest
     found).
  6. Whether DuckLake on DuckDB 2.0.1 has `ducklake_set_commit_message` and a native table rollback.
  7. The disk written by one full run (`du -sh data/lake`).
  8. The OpenLineage namespace and dataset names that dbt-ol/Cosmos emit when the profile `path` is `ops.duckdb` and
     the target `database` is the attached `warehouse` catalog. Phase 2 expects
     `duckdb:///opt/stack-data/warehouse.duckdb` and `warehouse.<schema>.<table>`. If the namespace changed, record
     the new value: Phase 2's `test_lineage.py` constant then changes as a **recorded identity change** (plan
     Complexity Tracking), not a weakened assertion.

  Also run `docker compose build && make up`: every service is healthy. **Do not start Phase 2 until this
  passes.**

**Checkpoint**: images build offline-ready; `upstream` and `opa` containers start (upstream may serve a stub until
T026); the open facts are written down.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: the data layers live in DuckLake and operational state in `ops.duckdb`, and every stack component uses
the new connection. Bronze is still filled from the shared generator through a **bridge** (generator → sources
store → copy into `bronze_raw` → Bronze tables). US1 replaces the copy step with `upstream` + dlt.

**⚠️ CRITICAL**: no user-story work begins until T023 passes.

### Tests (write first, confirm they fail)

- [X] T009 [P] Create `stack/tests/test_lake.py` (section "conexão"), using a tmp `ops.duckdb` and a **DuckDB-file DuckLake catalog** in `tmp_path`. Assert:
  - `warehouse.connect()` makes `warehouse` current;
  - `CREATE TABLE IF NOT EXISTS ops.autonomy_override (level VARCHAR)` lands in catalog `ops`, schema `main`;
  - `gold.*` / `bronze.*` tables created through the connection land in `warehouse`;
  - `SELECT schema_name FROM information_schema.schemata WHERE catalog_name='warehouse'` never contains `ops`, after a
    full bridge load too;
  - `autoinstall_known_extensions` is false and `extension_directory` points at `STACK_DUCKDB_EXTENSIONS`.
- [X] T010 [P] Create `stack/tests/test_bridge.py`. After the bridge load of a fresh scenario:
  - `bronze.campaigns`, `bronze.ad_spend` and `bronze.conversions` have the same column set as the default track's
    Bronze for the same `now`;
  - they have the same row count and the same `bit_xor(hash(row))` per `batch_id`;
  - `ops.campaigns` equals the generator's live state (PK present).

### Implementation

- [X] T011 In `src/agentready/generate.py`, extract `create_ops_tables(con)`: the three `ops.*` `CREATE TABLE`
  statements from `_reset`, same text, same order. Extract `seed_live_state(con, now)`: the `INSERT INTO
  ops.campaigns` executemany from `generate()`, same rows. `_reset` and `generate()` call them. There must be **no
  behavior change**. Run `uv run pytest -q` at the repo root: it passes with no test edits
- [X] T012 Create `stack/agentready_stack/src/agentready_stack/warehouse.py` per contracts/lake-snapshots.md →
  "Connection":
  - `connect(read_only=False)` opens `$AGENTREADY_DB`;
  - it sets `extension_directory=$STACK_DUCKDB_EXTENSIONS`, `autoinstall_known_extensions=false` and
    `autoload_known_extensions=true`;
  - it runs `ATTACH 'ducklake:$STACK_LAKE_CATALOG' AS warehouse (DATA_PATH '$STACK_LAKE_DATA')` and `USE warehouse`;
  - helpers `lake_snapshot_id(con)` (`max(snapshot_id)` from `ducklake_snapshots('warehouse')`) and
    `DATA_SCHEMAS = ("bronze_raw", "bronze", "quarantine", "silver", "gold", "meta", "elementary")`.

  Errors are raised in pt-BR, e.g. "extensão ducklake ausente em /opt/duckdb-extensions — reconstrua a imagem
  (make up)". Apply any fallback recorded in T008 #1.
- [X] T013 Update `stack/tests/conftest.py`: a fixture that sets `AGENTREADY_DB=<tmp>/ops.duckdb`,
  `STACK_LAKE_CATALOG=<tmp>/lake.ducklake`, `STACK_LAKE_DATA=<tmp>/lake/` and `STACK_DUCKDB_EXTENSIONS` for every
  stack test. Existing fixtures that open the warehouse switch to `warehouse.connect()`. Only fixture plumbing
  changes, never an assertion
- [X] T014 Replace every `connect` import from `agentready.db` in `stack/agentready_stack/src/agentready_stack/`
  (`tasks.py`, `incidents_cli.py`, `rollback.py`, `parity.py`, `ledger.py` if present, `observe.py`,
  `approvals.py` callers) with `warehouse.connect`. In `tasks._bronze_ready`, filter `table_catalog='warehouse'`
- [X] T015 Grep `stack/` and `docs/` for `warehouse.duckdb`, and update each hit to `ops.duckdb` or the lake, or justify keeping it. Known hits:
  - `stack/agentready_stack/src/agentready_stack/parity.py:144` (`AGENTREADY_DB` in the workdir → `ops.duckdb`, plus
    `STACK_LAKE_CATALOG=<workdir>/lake.ducklake`);
  - `stack/Dockerfile` `ENV` (T004);
  - `stack/dbt/aurora/profiles.yml` (T016);
  - `stack/dags/aurora_midia_diario.py:44` `WAREHOUSE_NS` (T017);
  - the Makefile help texts (`approvals`: "lê o warehouse"; `doctor` also lists the `ducklake`/`postgres` extension
    versions);
  - `stack/README.md` prose (T068).

  `tests/test_cli.py:46` tests the shared `db.connect()` with a tmp path. Leave it unchanged
- [X] T016 In `stack/dbt/aurora/profiles.yml`, both profiles (`aurora`, `elementary`):
  - `path: "{{ env_var('AGENTREADY_DB') }}"`;
  - `attach: [{path: "ducklake:{{ env_var('STACK_LAKE_CATALOG') }}", alias: warehouse, options: {data_path: "{{ env_var('STACK_LAKE_DATA') }}"}}]`;
  - `database: warehouse`;
  - `settings: {extension_directory: …, autoinstall_known_extensions: false}`;
  - `threads: 1` kept.
- [X] T017 In `stack/dags/aurora_midia_diario.py`, set `WAREHOUSE_NS` to the namespace recorded in T008 #8
  (unchanged if the spike confirms `duckdb:///opt/stack-data/warehouse.duckdb`), and confirm `ds()` still builds
  `warehouse.<schema>.<table>` (the lake is attached as `warehouse`). Run `stack/tests/test_lineage.py`
  **unchanged**. Only if T008 #8 found a new namespace: update that test's `WAREHOUSE_NS`/`LIVE_DB` constants, and
  confirm the Complexity Tracking row ("lineage namespace follows the dbt connection file") is in plan.md

  pt-BR comment: "camadas no DuckLake; estado operacional no ops.duckdb". Apply the T008 #4 fallback for
  `elementary` if recorded
- [X] T018 [P] In `stack/dbt/aurora/models/observabilidade/obs_esquema.py`, add `AND table_catalog = current_database()` to the `information_schema.columns` query (research R9). Grep `stack/` for other `information_schema` queries and do the same
- [X] T019 Create `stack/agentready_stack/src/agentready_stack/lake.py` with the checkpoint part only:
  - DDL for `ops.lake_checkpoints` exactly as data-model §4: `checkpoint_id` "`CK-<8 hex>`"; `dag_run_id` "NULL for
    checkpoints from commands"; `etapa` ∈ "`reset` · `ingestao.<fonte>` · `contratos` · `gold_observabilidade` ·
    `agente` · `restauracao`"; `snapshot_id` "`max(snapshot_id)` at that moment"; or NULL"; `lotes` "VARCHAR[]; the manifest's `lotes_novos` for `ingestao.<fonte>`; NULL for layer stages"; `criado_em`;
  - `checkpoint(con, etapa, dag_run_id=None, lotes=None) -> str`, which validates `etapa` against that list.
- [X] T020 Create `stack/agentready_stack/src/agentready_stack/ingestion.py` with the bridge parts that US1 keeps:
  - `rebuild_bronze(con, tables)`, exactly the statements in contracts/ingestion.md → "Bronze tables", tolerating a
    missing `_dlt_*` column (the bridge copy has none: use `EXCLUDE` only for columns that exist);
  - `store_call(fn_name, **kw)`: runs a shared function (`generate.generate`, `generate.backfill_meta`,
    `incidents.inject`, `incidents.resolve`) **in a subprocess** with `AGENTREADY_DB=/opt/stack-data/upstream/fontes.duckdb`
    and returns its JSON result. This is temporary; US1 replaces it with the `upstream` admin routes;
  - `bridge_load(con, store_path)`: `ATTACH store READ_ONLY AS fontes`;
    `CREATE OR REPLACE TABLE bronze_raw.<t> AS FROM fontes.bronze.<t>` for `ad_spend` and `campaigns`, and split
    `conversions` by `source` into `conversions__ga4` / `conversions__meta_capi`; `DETACH`;
    `rebuild_bronze`.

  The bridge copy function stays afterwards as the **reference loader** in tests.
- [X] T021 In `stack/agentready_stack/src/agentready_stack/tasks.py` → `ingest()`:
  - generate, backfill and incidents run on the sources store via `store_call`;
  - the incident row is mirrored into `ops.incidents` (same `incident_id`, `kind`, `injected_at`, `batch_id`). Create `ops.incidents` by calling the shared `incidents.open_incident(con)` **after `bridge_load`**, because `_ensure` also runs `CREATE TABLE IF NOT EXISTS meta.incident_backup AS SELECT * FROM bronze.conversions WHERE false`, which needs the Bronze view. The empty `meta.incident_backup` it leaves in the lake is unused on the stack (research R13 #9);
  - on reset, `generate.create_ops_tables(con)` + `generate.seed_live_state(con, now)` run on the stack connection,
    then `lake.checkpoint(con, "reset", dag_run_id)`;
  - then `bridge_load`.

  Keep the existing breaker/autonomy/`stack_run_settings` logic and the `ingestao.parametros` span unchanged. The
  "sem upstream ao vivo até a Fase 4" wording becomes "ponte: fontes geradas pelo gerador compartilhado" (it goes
  away in T035)
- [X] T022 In `stack/agentready_stack/src/agentready_stack/parity.py`, the stack side uses a workdir sources store
  plus `bridge_load` into `ducklake:<workdir>/lake.ducklake` with `<workdir>/ops.duckdb`. Run `_pin_arrivals` on the
  sources store before the copy. The default side is unchanged
- [X] T023 **Foundational gate**:
  - `uv run pytest -q` (repo root, unchanged);
  - `cd stack && make test` (all Phase 1–3 tests + T009/T010);
  - `make parity SCENARIO=todos` (0 diffs, report 2.1.0);
  - one live `make run ARGS='{"reset_scenario": true, "autonomy_override": "shadow"}'` (green; Phoenix trace
    present; `make observe` and `edr` report work). Also run the Phase 2 lineage checks (`stack/tests/test_lineage.py`, and in `make test-live` the Marquez path) after T017.

  Record the results in plan.md → Implementation Notes.

**Checkpoint**: the stack runs entirely on the lake + `ops.duckdb`; nothing user-visible changed yet.

---

## Phase 3: User Story 1 — Data arrives from failing upstream sources (Priority: P1) 🎯 MVP

**Goal**: four mock source systems serve the shared scenario over HTTP, failing deterministically. dlt loads each
one into the lake, and Block 5 incidents happen at the source.

**Independent Test**: reset and run once with no incident. Bronze is filled only by the four `ingestao.<fonte>`
tasks, every planted problem is in Bronze, and `make parity` reports 0 differences, including the new `bronze`
section (quickstart V-P4-4, V-P4-5).

### Tests for User Story 1 (write first, confirm they fail)

- [X] T024 [P] [US1] Create `stack/tests/test_upstream_api.py` (FastAPI `TestClient` over a tmp sources store generated by the shared generator). Assert:
  - the four `/…/v1/lotes` manifests (Meta's last 3 days absent before backfill, present after
    `POST /admin/meta/backfill`);
  - pagination `{"data", "page", "next_page"}` with stable order;
  - field values are strings byte-identical to the store (`"1,5"`, `"-30.00"`, `null` kept);
  - after `POST /admin/incidentes {"tipo": "renomeacao"}`, the batch's rows carry `utm_campaign` and no
    `campaign_id`, and other rows never carry `utm_campaign`;
  - the failure plan is deterministic: `padrao` fails only ga4 page 2 on the first attempt per `X-Execucao`, `todas`
    fails the first attempt of every page, and `fonte_fora_do_ar` always 503s; every 503 has `Retry-After: 1` and
    the pt-BR body;
  - a second open incident → 409 with pt-BR `erro`;
  - `/admin/*` on the public app → 404, and `/openapi.json` lists no admin route; the admin app (its own `TestClient`)
    serves them;
  - `deve_falhar` maps the param value `meta_capi` to the route prefix `/meta`.
- [X] T025 [P] [US1] Create `stack/tests/test_ingestion.py` (upstream's `public_app` started as a uvicorn subprocess on `127.0.0.1:<free port>` over a tmp store, waiting for `GET /saude`; scenario changes go through the shared functions on the store, not admin routes; the lake is a file catalog). Assert:
  - after `ingest-fonte` for all four sources, Bronze == the T020 reference loader's Bronze (columns, rows and
    checksum per batch);
  - the planted problems are present: the `-retry` batch, the broken old batch, `C99`, NULL `campaign_id`, comma
    decimals;
  - `ingested_at` is a naive `TIMESTAMP` equal to the source's `delivered_at`;
  - with `falhas_upstream=todas`, row counts per batch are identical (SC-003);
  - a mid-pagination failure (`deve_falhar` monkeypatched to fail page 3 forever; no test-only mode is served) gives status `falhou` and leaves
    `bronze_raw` unchanged;
  - `fonte_fora_do_ar=ga4` → ga4 `falhou` with motivo `ga4: fonte indisponível após 4 tentativas (503)`, while the
    others are `carregado`;
  - a second run with unchanged sources → `sem_dados_novos` for all, and **no new lake snapshot**;
  - `ops.ingestion_loads` rows follow data-model §4: `status` ∈ "`carregado` · `sem_dados_novos` · `falhou`";
    `motivo` "pt-BR, required when `falhou`"; `linhas` "NULL when not `carregado` (never 0 for 'unknown',
    Principle III)"; `snapshot_id` "NULL unless `carregado`"; and the diff is computed against the last
    **`carregado`** row;
  - a monkeypatched `agentready.generate` that raises proves the ingest path never calls the generator;
  - `/opt/venvs/ingest/bin/python -c "import agentready_stack.ingestion, agentready_stack.lake, agentready_stack.telemetry"`
    succeeds (the ingest venv has every import it needs).
- [X] T026 [P] [US1] Create `stack/tests/test_dag_phase4.py` (same Airflow fixture as `test_dag_integrity.py`). Assert:
  - task group `ingestao` has `parametros`, `ads`, `ga4`, `meta_capi` and `catalogo`, wired as in
    contracts/dag-interface.md;
  - each source task has `retries=0` and the inlet/outlet assets from the table;
  - params `falhas_upstream` (default `padrao`, enum `padrao|nenhuma|todas`) and `fonte_fora_do_ar` (default
    `nenhuma`, enum `nenhuma|ads|ga4|meta_capi|catalogo`);
  - tags include `stack-fase-4` and `bloco-3`.

### Implementation for User Story 1

- [X] T027 [US1] Create `stack/agentready_stack/src/agentready_stack/upstream_app.py` per contracts/upstream-api.md:
  - the FastAPI app (`title="Fontes da Aurora (simuladas)"`, pt-BR descriptions per route);
  - one DuckDB connection to `$AGENTREADY_DB` (the sources store), guarded by a lock;
  - source routes over the store's `bronze.*` (conversions split by `source`);
  - manifests with an order-independent checksum;
  - the `renomeacao` serialization rule;
  - a separate `admin_app` (port 8001; never published) with the admin routes, calling the shared `generate.generate`, `generate.backfill_meta`,
    `incidents.inject` and `incidents.resolve`. Exceptions → 409 `{"erro": <pt-BR message>}`;
  - `GET /admin/saude` on the admin app, and `GET /saude` on the public app;
  - `main()` serves `public_app` on 8000 and `admin_app` on 8001 in one process (two uvicorn servers sharing the
    store connection and lock), so `python -m agentready_stack.upstream_app` is the entrypoint.

  If the store has no tables on startup, generate the scenario once.
- [X] T028 [US1] In `upstream_app.py`, add the failure plan:
  - `PUT /admin/falhas` stores `{execucao: (falhas_upstream, fonte_fora_do_ar)}` in memory;
  - an attempt counter keyed by (execucao, route, page);
  - the pure decision function `deve_falhar(plano, execucao, rota, pagina, tentativa) -> bool` per the table in
    contracts/upstream-api.md;
  - 503 responses carry `Retry-After: 1` and `{"erro": "indisponível temporariamente"}`. The failure plan uses the load-record source names; `meta_capi` maps to the route prefix `/meta`.
- [X] T029 [P] [US1] Create `stack/ingestion/fontes.yaml`: the dlt REST API source config for `ads`, `ga4`, `meta`
  and `catalogo`, per contracts/ingestion.md:
  - base_url from `UPSTREAM_URL`, header `X-Execucao`;
  - page-number paginator, `page_size: 500`, `data_selector: data`;
  - retries: max 4, exponential, respect `Retry-After`;
  - resources `ad_spend`, `conversions__ga4`, `conversions__meta_capi`, `campaigns`, with
    `write_disposition: replace`;
  - column hints `* → text`, `ingested_at → timestamp, timezone: false` (syntax per T008 #2).

  Also set `runtime.dlthub_telemetry: false` (in case the env var is missing). pt-BR comments explain why it's
  replace plus change detection (research R5).
- [X] T030 [US1] In `stack/agentready_stack/src/agentready_stack/ingestion.py`, implement
  `run_source(fonte, dag_run_id)` per contracts/ingestion.md → "Algorithm":
  - manifest GET with the same retry policy;
  - diff against the last `carregado` row;
  - `sem_dados_novos` short-circuit;
  - the dlt pipeline from `fontes.yaml` with a temp `pipelines_dir`, dlt `filesystem` destination (Parquet) in a temp bucket, then the one-transaction commit into
    `warehouse.bronze_raw` (contracts/ingestion.md step 5);
  - on success, `rebuild_bronze` in the commit transaction, `linhas`, `snapshot_id = warehouse.lake_snapshot_id(con)` and
    `lake.checkpoint(con, f"ingestao.{fonte}", dag_run_id, lotes=lotes_novos)`;
  - catch every load exception → `falhou` with a pt-BR motivo;
  - create and insert into `ops.ingestion_loads` with the exact data-model §4 columns
    (`load_id` "`LD-<8 hex>`", `lotes_novos/retirados/inalterados` VARCHAR[], `manifesto` JSON,
    `tentativas_http` INTEGER, `iniciado_em/terminado_em`);
  - print the pt-BR summary line, then the JSON result as the last stdout line;
  - exit 0 for every status, exit 1 only for configuration errors.
- [X] T031 [P] [US1] In `stack/agentready_stack/src/agentready_stack/telemetry.py`, add the `ingestao.carga` span
  helper per contracts/dag-interface.md → "Span catalog delta": attributes `agentready.fonte`, `.status`,
  `.lotes_novos`, `.lotes_retirados`, `.linhas` (**omitted if NULL**), `.tentativas_http`, `.snapshot_id`, plus run
  attrs. ERROR with the pt-BR motivo when `falhou`. Call it from `run_source`
- [X] T032 [US1] In `stack/agentready_stack/src/agentready_stack/cli.py`, add `task ingest-fonte <ads|ga4|meta_capi|catalogo> --dag-run-id ID` (it runs `ingestion.run_source`, attaching TRACEPARENT and flushing like the other task subcommands) and `fontes` (the last load per source from `ops.ingestion_loads` as a pt-BR table, last line JSON)
- [X] T033 [US1] In `stack/dags/aurora_midia_diario.py`:
  - the `ingestao` group becomes `parametros` + four source tasks, wired as in contracts/dag-interface.md. Source
    tasks run `agentready-stack task ingest-fonte <fonte>` with the **ingest** venv (add a `venv` argument to
    `run_stack()`, default `agent`), `retries=0`, the same pool, and the inlet/outlet assets from the table
    (`fonte://…` inlets via the existing `ds()` helper or an equivalent asset builder);
  - add params `falhas_upstream` and `fonte_fora_do_ar` with the defaults and enums from the contract and pt-BR
    descriptions;
  - add tags `stack-fase-4`, `bloco-3`;
  - pt-BR docstrings.
- [X] T034 [US1] In `stack/agentready_stack/src/agentready_stack/tasks.py` → `ingest()` (now the `parametros`
  step), replace `store_call` with HTTP calls to `$UPSTREAM_ADMIN_URL` (port 8001):
  - `PUT /admin/falhas` with the run's plan;
  - `POST /admin/cenario/reset` on reset (or when Bronze isn't ready);
  - `POST /admin/meta/backfill`;
  - `POST /admin/incidentes`, whose returned row is mirrored into `ops.incidents`. Keep the T021 order: `ops.incidents` is created after the first source load, not before.

  Remove the `bridge_load` call (ingestion is now the source tasks). A 409 from upstream is raised with its pt-BR
  message. Add attributes `agentready.falhas_upstream` and `agentready.fonte_fora_do_ar` to `ingestao.parametros`
- [X] T035 [US1] In `stack/agentready_stack/src/agentready_stack/ingestion.py`, delete `store_call` from the
  production path. Keep `bridge_load` only as the test reference loader: move it to `stack/tests/_reference.py` if
  nothing in production imports it. Update the `tasks.py` pt-BR wording to describe live sources
- [X] T036 [US1] In `stack/agentready_stack/src/agentready_stack/incidents_cli.py`, for this story: `resolve` calls
  `POST $UPSTREAM_ADMIN_URL/admin/incidentes/resolver`, then marks `ops.incidents` resolved (TTD/TTR via `incidents.metrics`).
  `detect`, `reveal` and `list` read the `ops.incidents` mirror. US2 (T050) adds the lake restore
- [X] T037 [US1] In `stack/agentready_stack/src/agentready_stack/parity.py`, the stack side follows
  contracts/parity.md → "Stack side procedure" steps 1–3 and 5 (store + `_pin_arrivals` + uvicorn subprocess on a
  free port + `ingest-fonte` ×4 into the workdir file catalog). Add the `compared.bronze` and `compared.ingestion`
  sections exactly as specified, and bump the report to `2.2.0`. Create
  `stack/agentready_stack/src/agentready_stack/parity-report.schema.json` 2.2.0 (or the existing schema location)
  from 2.1.0 + `bronze` + `ingestion` (+ `policy`, filled by T066)
- [X] T038 [P] [US1] Create `stack/tests/test_parity_v22.py`: on scenario `manha`, `compared.bronze` and
  `compared.ingestion` have 0 diffs and the report validates against schema 2.2.0. A deliberately altered Bronze
  value on the stack side is reported with `{table, batch_id, field, default, stack}`
- [X] T039 [P] [US1] In `stack/scripts/lineage_live_check.py`, add a check that Marquez lists the four `fonte://…`
  datasets upstream of `bronze.*` after a run (FR-007)
- [X] T040 [P] [US1] In `stack/Makefile`, add the `fontes` target (`agentready-stack fontes`). Update the `run` help
  to mention `falhas_upstream` / `fonte_fora_do_ar`
- [X] T041 [US1] **Live validation US1** (shadow): quickstart V-P4-3 → V-P4-10 (all four incidents; `make
  incidente ACAO=resolver` uses the T036 behavior). `make parity SCENARIO=todos`: 0 diffs in every section. Record
  the results in plan.md → Implementation Notes

**Checkpoint**: Bronze comes only from the sources; Blocks 1 and 5 behave exactly as before; parity 2.2.0 is green.

---

## Phase 4: User Story 2 — Undo a bad batch by going back to a snapshot (Priority: P2)

**Goal**: named checkpoints, "Gold as of a decision", and incident resolve by an undoable restore that never
touches `ops`.

**Independent Test**: clean run → `centavos` run → `make incidente ACAO=resolver` → Gold and source health equal the
clean run's `agente` checkpoint exactly; the restore is listed and can be undone (quickstart V-P4-11, V-P4-12).

### Tests for User Story 2 (write first, confirm they fail)

- [X] T042 [P] [US2] Extend `stack/tests/test_lake.py` (section "snapshots"; a new file is fine if preferred). Assert:
  - `checkpoint()` rejects an unknown `etapa`;
  - `snapshots()` labels raw snapshots with the last checkpoint ("(sem marca) após <etapa>");
  - `gold_as_of()` resolves a trace id, a `CHG-…` (via `change_log.trace_id`) and a `REQ-…` (via
    `approval_queue.trace_id`) to the run's `agente` checkpoint, returns the Gold rows read at that snapshot, and
    exits 1 for an unknown key;
  - `restore(n)` leaves every data table equal to its read `AT (VERSION => n)`, drops a table created after n,
    restores the Bronze tables, creates exactly **one** new snapshot, keeps later snapshots listed, and is undoable
    (restore to the previous `de` gives the earlier state back);
  - the `ops.*` table checksums are identical before and after every restore;
  - `ops.lake_restores` matches data-model §4 (`restore_id` "`RS-<8 hex>`"; `de_snapshot`, `para_snapshot`,
    `novo_snapshot`, `por`, `motivo`, `incident_id` nullable, `feito_em`) and a `restauracao` checkpoint is added;
  - `consultar_em(con, tabela, em)` returns the table's rows at a snapshot id and at a timestamp, refuses `ops.*`
    (exit 2) and an unknown table (exit 1);
  - the guards refuse with exit code 2 and a pt-BR message: an active run (Airflow API monkeypatched), a target
    before the last `reset` checkpoint, a nonexistent target, the current snapshot.
- [X] T043 [P] [US2] Create `stack/tests/test_incident_resolve_lake.py`. Scenario: clean ingestion + build +
  `agente` checkpoint → `centavos` injected at the source + ingestion + build. Then `incident resolve`:
  - the upstream resolve was called;
  - the lake was restored to the last `agente` checkpoint before `injected_at`;
  - Gold and `gold.source_health` equal the clean checkpoint's reads exactly;
  - TTD/TTR are set;
  - with no prior `agente` checkpoint, it falls back to the latest checkpoint before `injected_at` and warns in
    pt-BR;
  - `ops.campaigns` and `ops.change_log` are untouched.

### Implementation for User Story 2

- [X] T044 [US2] In `stack/agentready_stack/src/agentready_stack/lake.py`, add `snapshots(con, limit=30)`: join
  `ducklake_snapshots('warehouse')` with `ops.lake_checkpoints` and `ops.lake_restores`. Each row has the snapshot, the
  local time, the label, the run, the batches (`lotes`), the incident and the tables changed. Also add
  `consultar_em(con, tabela, em)` (FR-009): a read-only `SELECT … FROM <tabela> AT (VERSION => n)` or
  `AT (TIMESTAMP => t)`, refusing any `ops.*` table
- [X] T045 [US2] In `lake.py`, add `gold_as_of(con, key)` per data-model §5. It returns the run, snapshot, the
  decision's campaign, the Gold rows over the guardrails `lookback_days`, and the cited value (from
  `change_log`/`approval_queue` params and the audit record's `tool.*` span attributes for that trace)
- [X] T046 [US2] In `lake.py`, add `restore(con, target, motivo, por="instrutor", incident_id=None)` per
  contracts/lake-snapshots.md → "Restore algorithm":
  - the three pre-checks, where the active-run check calls Airflow's REST API
    `GET /api/v2/dags/aurora_midia_diario/dagRuns?state=running&state=queued` with the instrutor credentials from
    `config/passwords.json` (same mechanism `make run` uses);
  - one transaction over `warehouse.DATA_SCHEMAS` (never `ops`): CTAS from `AT (VERSION => n)`, drop tables newer
    than n;
  - record `ops.lake_restores` + a `restauracao` checkpoint.

  If T008 #6 found a native rollback that yields a new snapshot, use it behind the same function
- [X] T047 [P] [US2] In `telemetry.py`, add the `lake.checkpoint` and `lake.restauracao` span helpers per the span
  catalog delta (`lake.restauracao` is ERROR when refused). Call them from `lake.py`
- [X] T048 [US2] In `stack/agentready_stack/src/agentready_stack/tasks.py`, call `lake.checkpoint` at the start of
  `quality_alert()` (`contratos`), `observe()` when called from `observabilidade.resumo` (`gold_observabilidade`),
  and `run_agent()` **before** the ledger/agent reads (`agente`), passing `dag_run_id`. Do these in sequence; it's
  the same file as T034
- [X] T049 [US2] In `stack/agentready_stack/src/agentready_stack/cli.py`, add `snapshots [--limit N]`,
  `consultar-em <schema.tabela> <snapshot|AAAA-MM-DDTHH:MM> [--filtro SQL] [--limite N]` (exit 1 unknown table, 2 `ops` refused),
  `gold-em <key>` and `restaurar <snapshot|CK-…> [--motivo T] [--por ATOR]`, with pt-BR tables, a last-line JSON,
  and the exit codes from contracts/commands.md (gold-em 1 not found; restaurar 2 refused). The restaurar output
  prints the undo hint `make restaurar PARA=<de>`
- [X] T050 [US2] In `stack/agentready_stack/src/agentready_stack/incidents_cli.py` → `resolve`, implement
  contracts/lake-snapshots.md → "Incident resolve" steps 1–5 (upstream resolve → target checkpoint → `lake.restore`
  with `motivo = "incidente <id> resolvido"` → TTD/TTR). Exit 1 if none open, 2 if the restore is refused The upstream call uses `$UPSTREAM_ADMIN_URL`.
- [X] T051 [US2] In `stack/Makefile`, add the targets `snapshots`, `consultar-em TABELA=… EM=… [FILTRO=…]`, `gold-em DECISAO=…` and `restaurar PARA=… [MOTIVO=…]`
  with pt-BR help. Change `incidente`: `ACAO=resolver` **no longer triggers `make run`**; the message says "camadas
  restauradas para o último estado limpo; a próxima execução busca o lote corrigido na fonte"
- [X] T052 [US2] **Live validation US2**: quickstart V-P4-11, V-P4-12, V-P4-13 (shadow; for V-P4-13 start a run and
  try a restore while it's running). Record the snapshot ids, the timings (restore ≤ 30 s, `gold-em` ≤ 5 s) and the
  results in plan.md → Implementation Notes

**Checkpoint**: Block 5 recovery is a time travel; the restore is undoable; `ops` is provably untouched.

---

## Phase 5: User Story 3 — Guardrails as a policy anyone can test (Priority: P3)

**Goal**: on the stack, OPA decides every write action with today's exact check ids and details, through one shared
evaluator call. The default track keeps its in-process evaluator. Fail closed.

**Independent Test**: `make politica-testes` passes; `make politica ACAO='ajustar C01 5200'` → `NEGADO
(variacao_maxima)`; parity `policy` and `traces` sections have 0 diffs; with OPA stopped, 0 actions execute
(quickstart V-P4-14, V-P4-15).

### Tests for User Story 3 (write first, confirm they fail)

- [X] T053 [P] [US3] Create `tests/test_policy.py` (repo root, **new file**; existing default tests stay untouched). Assert:
  - for a matrix of facts covering every check id passing and failing, `policy.LocalEvaluator` + `describe()`
    produce the same `(id, passed, detail)` list as the pre-change logic, with the expected detail strings pinned
    in the test (copied from today's `capabilities.py` format, e.g.
    `"R$ 4.000,00 -> R$ 5.200,00 (+30%); limite ±20%"`);
  - `campanha_existe=false` returns only that check;
  - `dados_frescos` is absent when `require_fresh_sources` is false;
  - `evaluator()` returns `LocalEvaluator` when `AGENTREADY_POLICY_EVALUATOR` is unset and loads `module:Class`
    when set;
  - `evaluate()` returns exactly `[Check("politica_avaliada", False, "não foi possível avaliar a política: …")]`
    when the evaluator raises;
  - the action span gets `policy.evaluator` and `policy.version`.
- [X] T054 [P] [US3] Create `stack/tests/test_policy_equivalence.py` (needs the `opa` service, like Postgres for other tests). Assert:
  - every case in `stack/policy/casos.yaml` gives identical ids, verdicts, order and `describe()` text through
    `LocalEvaluator` and `OpaEvaluator`;
  - each check id appears in ≥ 1 passing and ≥ 1 failing case (data-model §6: "every check id appears in ≥ 1 case as
    passing and ≥ 1 as failing");
  - **mutation**: for each numeric limit and list, write a temp copy of `config/guardrails.yaml` with that value
    changed. Evaluate the cases with `docker compose run --rm -v <tmp>:/m:ro opa eval -d /policy -d
    guardrails:/m/guardrails.yaml -i … 'data.agentready.guardrails.decisao'` (a one-off container), and run
    `LocalEvaluator` with a monkeypatched `settings.guardrails`. ≥ 1 case must change verdict (SC-006). **Never write
    to the live `opa` service's data.**
- [X] T055 [P] [US3] Create `stack/tests/test_policy_fail_closed.py`. With `OPA_URL` pointing at a closed port, a
  server that sleeps 5 s, a 500, and a malformed `result` (unknown id or wrong order): `adjust_campaign_budget`
  returns `rejected` with `politica_avaliada`, `ops.campaigns` and `ops.change_log` are unchanged, and every call
  returns in ≤ 2.5 s. `_execute_approved` (an approved request) is also rejected when OPA is down. Read-only
  capabilities never call the evaluator Also: with OPA down **before** the agent step, `run_agent` raises the pt-BR preflight error (`política indisponível ou inválida: o agente não roda (falha fechada)`) and creates no ledger row.

### Implementation for User Story 3

- [X] T056 [US3] Create `src/agentready/policy.py` per contracts/policy-interface.md:
  - `Fatos` (fields exactly as data-model §6), `Decisao`, `Evaluator` protocol;
  - `LocalEvaluator` with the comparisons **moved verbatim** from `capabilities._common_checks` /
    `budget_checks`, reading `settings.guardrails()`;
  - `describe()`, which produces today's pt-BR detail strings byte-for-byte using `capabilities.brl` (move `brl` to
    `policy.py` and re-export it from `capabilities` if needed to avoid a circular import);
  - `evaluator()`, loaded from `AGENTREADY_POLICY_EVALUATOR`;
  - `evaluate(acao, fatos) -> list[Check]`, never raising (fail closed);
  - the version from `stack/policy/VERSION` if present, else `local-<guardrails.version>`.
- [X] T057 [US3] In `src/agentready/capabilities.py`, `_common_checks` and `budget_checks` keep their queries and
  return types, build `policy.Fatos`, and return `policy.evaluate(...)`. Add `policy.evaluator` and
  `policy.version` to the action span in `adjust_campaign_budget` / `pause_campaign`. `_gate`,
  `_execute_approved`, `decide_approval` and `rollback` are unchanged. Run `uv run pytest -q` (unchanged suite +
  T053) and `cd stack && make test` (Phase 1–3 approval/agent tests unchanged)
- [X] T058 [P] [US3] Create `stack/policy/VERSION` (`1.0.0`) and `stack/policy/guardrails.rego`:
  - `package agentready.guardrails`, Rego v1;
  - `versao` read from data (or a constant equal to VERSION, kept equal by a test);
  - `decisao` returning `{"permitido", "checagens", "versao"}` with `checagens` in today's order (common checks,
    then budget checks only for `adjust_campaign_budget`; only `campanha_existe` when it fails; `dados_frescos`
    only if `data.guardrails.data.require_fresh_sources`);
  - every limit read from `data.guardrails`, **never hard-coded**;
  - `valores` per check, carrying the numbers `describe()` needs.

  pt-BR comments.
- [X] T059 [P] [US3] Create `stack/policy/casos.yaml`: ≥ 1 passing and ≥ 1 failing case per check id
  (`campanha_existe`, `campanha_ativa`, `sem_trava_humana`, `objetivo_elegivel`, `justificativa_presente`,
  `dados_frescos`, `variacao_maxima`, `orcamento_minimo`, `teto_do_portfolio`, `limite_de_alteracoes`), both
  actions, boundary values (exactly ±20%, exactly the minimum, exactly the cap), and the `gullible` case (C01 asking
  for the larger change)
- [X] T060 [US3] Create `stack/policy/guardrails_test.rego`: for every case in `data.casos`, the set of failed ids
  in `decisao` equals `esperado_falhas`. Confirm `docker compose run --rm opa test /policy /policy/casos.yaml` (plus
  the guardrails data as in T005c) passes
- [X] T061 [US3] Create `stack/agentready_stack/src/agentready_stack/policy_opa.py`: `OpaEvaluator` (`nome="opa"`).
  It POSTs to `$OPA_URL/v1/data/agentready/guardrails/decisao` with a 2 s timeout and no retries, validates the
  response (known ids, local order, types) and raises on anything else, so `policy.evaluate` fails closed. Returns
  `Decisao` with OPA's `versao`
- [X] T062 [US3] In `stack/compose.yaml`, enable `AGENTREADY_POLICY_EVALUATOR=agentready_stack.policy_opa:OpaEvaluator`
  in `x-airflow-common`. Add `opa` to the scheduler/worker `depends_on` (healthy if a healthcheck exists). pt-BR
  comment: "Fase 4: guardrails decididos pelo OPA; sem OPA, nenhuma escrita (falha fechada)"
- [X] T063 [US3] In `stack/agentready_stack/src/agentready_stack/policy_opa.py`, add `preflight()` per
  contracts/policy-interface.md → "Preflight" (`GET $OPA_URL/health?bundles` plus a decision on a fixed probe input,
  2 s timeout each, schema check). In `stack/agentready_stack/src/agentready_stack/tasks.py` → `run_agent()`, call
  it **before the ledger** when `AGENTREADY_POLICY_EVALUATOR` is set. On failure, raise in pt-BR: "política
  indisponível ou inválida: o agente não roda (falha fechada)", so the task fails and nothing executes. Per-action
  fail-closed (T061) still covers OPA going down mid-run. This is the same file as T048, so do it after T048
- [X] T064 [US3] In `stack/agentready_stack/src/agentready_stack/cli.py`, add
  `politica <acao> <campanha> [<novo_orcamento>] [--justificativa T]`. It builds `Fatos` from the live state with
  the shared capability helpers (no copied queries), asks `policy.evaluator()`, and prints a pt-BR table plus
  `PERMITIDO` / `NEGADO (<ids>)`. Exit 0 / 3 / 1 per contracts/policy-interface.md. It never executes anything
- [X] T065 [US3] In `stack/Makefile`:
  - add `politica ACAO='ajustar C01 5200' | ACAO='pausar C06'`, translating to the CLI;
  - add `politica-testes` (`opa test -v`);
  - `test` also runs `opa test` and fails with "Rode 'make up' antes de 'make test'" if `opa` isn't running (same
    pattern as the Postgres check).
- [X] T066 [US3] In `stack/agentready_stack/src/agentready_stack/parity.py`:
  - the stack side runs the agent with `AGENTREADY_POLICY_EVALUATOR=…OpaEvaluator` and `OPA_URL=http://opa:8181`
    (step 4);
  - fill `compared.policy` (action checks from both sides' spans + the `casos.yaml` matrix through both
    evaluators) per contracts/parity.md;
  - trace normalization ignores exactly one new key, `policy.evaluator` (mapping R7); `policy.version` must be
    equal.

  Extend `stack/tests/test_parity_v22.py` with the `policy` section assertions
- [ ] T067 [US3] **Live validation US3**: quickstart V-P4-14 and V-P4-15. For the "approve while OPA is down" step,
  **stop and ask the user** to approve as `aprovadora`, and report what they saw. `make parity SCENARIO=todos`: 0
  diffs in every section. Record the results in plan.md → Implementation Notes

**Checkpoint**: Block 3 on the stack is decided by OPA, provably identical to the default track, and fails closed.

---

## Phase 6: User Story 4 — The guide and instructor script cover Phase 4 (Priority: P3)

**Goal**: a newcomer can present and run Phase 4 from the docs alone.

**Independent Test**: following only `stack/README.md`, a newcomer gets a run fed by the sources, a failing policy
test after editing a copy, and an incident resolved by restore (quickstart V-P4-16).

- [X] T068 [P] [US4] Update `stack/README.md` (pt-BR):
  - (a) intro sentence: add "fontes que falham de verdade (dlt), guardrails como política (OPA) e snapshots
    (DuckLake) (Fase 4)";
  - (b) prerequisites: the new peak RAM and disk per run (from T073);
  - (c) quick start: `make fontes`, `make snapshots`, `make politica`;
  - (d) the replacement map gets a "Fase 4" table with the four rows from plan.md → "Replacement map additions",
    including the **partial** note for `ops.duckdb`;
  - (e) "Lacunas conhecidas": remove the "sem nó por fonte até a Fase 4" item; add the eight gaps from research
    R13;
  - (f) the roadmap marks Phase 4 ✅, with the reason MinIO was left out (source-only since 2025-10, with sources)
    and "DuckLake 1.1 é versão nova (out/2026)";
  - (g) a new section "Blocos 1, 3 e 5 na trilha stack (Fase 4)": show `:8000/docs`, a run with
    `falhas_upstream`/`fonte_fora_do_ar`, `make politica-testes` + editing a copy of the limits, `make consultar-em` (any table as of a snapshot or a
    time), and the
    `centavos` → `incidente ACAO=resolver` → `snapshots` → `restaurar` flow;
  - (h) the `run` params table gets `falhas_upstream` and `fonte_fora_do_ar`;
  - (i) "Tempos medidos" gets a "Fase 4" subsection with "a medir" rows for SC-010.
- [X] T069 [P] [US4] Update `docs/01-roteiro-do-instrutor.md` (pt-BR): stack-track notes for Block 1 (the sources'
  `/docs`, the retry in the log, the duplicate batch still caught by the contract), Block 3 (OPA decides; the
  same checks in the trace; `make politica`; fail closed) and Block 5 (resolve by snapshot restore; "o dado volta,
  o dinheiro não: rollback de orçamento continua pelo change log"). Match the default-track teaching points
- [X] T070 [P] [US4] Update `docs/02-exercicios.md` (pt-BR): stack variants of the Block 1 exercise (find the
  redelivered batch in `make fontes` and in quarantine), Block 3 (break a limit in a copy and watch `make
  politica-testes` fail; ask `make politica`), and Block 5 (`make gold-em` for a contaminated decision, then
  resolve and undo)
- [X] T071 [US4] Check that `README.md` (repo root) and `docs/03-visao-de-negocio.md` don't contradict Phase 4.
  Update only stale stack-phase mentions, in pt-BR

**Checkpoint**: the docs describe the finished behavior and its honest gaps.

---

## Phase 7: Polish & Cross-Cutting Concerns

- [ ] T072 In `stack/scripts/lineage_live_check.py` (or a renamed `live_check.py`, with the Makefile updated),
  add the `make test-live` checks from contracts/commands.md:
  - a run fed by the sources;
  - `fonte_fora_do_ar=ga4` (the others load, ga4 `falhou`, the run finishes);
  - OPA stopped before a run: `agente.executar` fails with the preflight message (`política indisponível ou
    inválida…`), 0 executed, no hang; then OPA is restarted and the next run is green;
  - `centavos` → resolve → Gold == the pre-incident clean checkpoint → undo restore → redo.

  All in shadow mode
- [ ] T073 Measure and record in `stack/README.md` and plan.md → Implementation Notes: the peak RAM across all
  containers during a full run (`docker stats --no-stream`, SC-008, must stay within 8 GB), `du -sh data/lake`
  after one and after ten runs, the ingestion time for all four sources (target ≤ 60 s), and the full-run time
  compared with Phase 3 (target ≤ +90 s)
- [ ] T074 Offline check (V-P4-16, FR-020): after the images are built, disconnect the network, then `make up` and
  `make run ARGS='{"autonomy_override": "shadow"}'`. There must be no extension or package download (autoinstall
  is off) and no OPA telemetry. If it can't be done here, leave it to the user and say so Also confirm: no outbound request to dlthub (dlt telemetry off), and `upstream` answers only on `127.0.0.1:8000` (8001 unpublished).
- [ ] T075 **Full gate**:
  - `uv run pytest -q` (repo root: unchanged suite + `tests/test_policy.py`);
  - `cd stack && make test`;
  - `make politica-testes`;
  - `make parity SCENARIO=todos` (0 diffs in every section, report 2.2.0);
  - `make test-live`;
  - then a **clean-checkout** run (`git clone` into a temp dir, `make test` → asks for `make up`; `make up`;
    `make run`; `make fontes` all `carregado`/expected; `make snapshots` lists checkpoints).

  Record it in plan.md and in the README's "Tempos medidos"
- [ ] T076 Leave for the user (don't simulate): **SC-010** (a newcomer resolves `centavos` by restore from the
  guide in ≤ 10 min) needs a person with a stopwatch. Add it as an "a medir" row in the README's timing table, and
  tell the user in the final report
- [ ] T077 Update `specs/004-stack-ingestion-policy-snapshots/spec.md` **Status** to "Implemented" (listing any
  pending manual validations) and close out every Implementation Notes item in plan.md (versions pinned, spike
  facts, fallbacks taken, measured numbers)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Setup + spike gate)**: no dependencies. **T008 gates everything after it.**
- **Phase 2 (Foundational)**: after T008. **T023 gates every story.**
- **US1 (Phase 3)**: after Phase 2. This is the MVP.
- **US2 (Phase 4)**: after Phase 2. It can be built on the bridge, but its live validation (T052) and T050's
  upstream resolve need US1's `upstream` (T027, T036). Do T050 after T036 (same file).
- **US3 (Phase 5)**: after Phase 2. Independent of US1/US2 except: T066 edits `parity.py` after T037, T065 edits
  the Makefile after T040/T051, and T063 edits `tasks.py` after T048 (same files, so in sequence).
- **US4 (Phase 6)**: after the stories it documents, and after T073 for the numbers.
- **Polish (Phase 7)**: last.

### Same-file sequences (don't parallelize)

- `tasks.py`: T014 → T021 → T034 → T035 → T048 → T063
- `ingestion.py`: T020 → T030 → T035
- `parity.py`: T014 → T015 → T022 → T037 → T066
- `cli.py`: T032 → T049 → T064
- `incidents_cli.py`: T014 → T036 → T050
- `lake.py`: T019 → T044 → T045 → T046
- `stack/Makefile`: T007 → T015 → T040 → T051 → T065 → (T072 if renamed)
- `stack/compose.yaml`: T005 → T062
- `telemetry.py`: T031 → T047
- `stack/dags/aurora_midia_diario.py`: T017 → T033
- `policy_opa.py`: T061 → T063
- T015 (the `warehouse.duckdb` sweep) touches several files: run it right after T014 and before T016–T017

### Within Each User Story

- Tests first (they must fail), then implementation, then the live validation task at the end of the phase.

### Parallel Opportunities

- Phase 1: T001, T002, T003 and T006 together, then T004 → T005 → T007 → T008.
- Phase 2: T009 and T010 (tests) together. T011 (shared) is independent of T012–T018. T018 is independent of the
  rest.
- US1: tests T024, T025 and T026 together. Then T027 → T028 (same file), with T029 and T031 in parallel. T038, T039
  and T040 in parallel after T037.
- US2: tests T042 and T043 together. T047 in parallel with T044–T046.
- US3: tests T053, T054 and T055 together. T058 and T059 together. T056 → T057 is sequential (shared code). T061 can
  start once T056's protocol exists.
- US4: T068, T069 and T070 together.

---

## Parallel Example: User Story 1

```bash
# Tests first, in parallel (different files):
Task: "T024 [US1] upstream API tests in stack/tests/test_upstream_api.py"
Task: "T025 [US1] ingestion tests in stack/tests/test_ingestion.py"
Task: "T026 [US1] DAG Phase 4 tests in stack/tests/test_dag_phase4.py"

# Then:
Task: "T027 → T028 [US1] upstream_app.py"          # same file, in sequence
Task: "T029 [US1] stack/ingestion/fontes.yaml"      # parallel
Task: "T031 [US1] ingestao.carga span in telemetry.py"  # parallel
```

## Parallel Example: User Story 3

```bash
Task: "T053 [US3] tests/test_policy.py (default track, new file)"
Task: "T054 [US3] stack/tests/test_policy_equivalence.py"
Task: "T055 [US3] stack/tests/test_policy_fail_closed.py"
# then
Task: "T058 [US3] stack/policy/guardrails.rego + VERSION"
Task: "T059 [US3] stack/policy/casos.yaml"
```

---

## Implementation Strategy

### MVP First (User Story 1 only)

1. Phase 1, including the spike gate T008.
2. Phase 2: the lake + `ops.duckdb` on the bridge, with all Phase 1–3 tests and parity green (T023).
3. Phase 3 (US1): sources + dlt + incidents at the source; parity 2.2.0 `bronze`/`ingestion` at 0.
4. **Stop and validate**: Blocks 1 and 5 run on data that *arrives*, and nothing the agent decides has changed.

### Incremental Delivery

1. + US2: snapshots, `gold-em`, resolve by an undoable restore.
2. + US3: OPA decides, with equivalence proven, fail closed.
3. + US4: guide, script, exercises.
4. Polish: test-live, RAM/disk, offline, clean checkout. The user times SC-010.

---

## Notes

- [P] tasks = different files, no dependency on an unfinished task.
- Commit after each task or logical group. Never commit `stack/.env`, `stack/config/passwords.json` or anything
  under `stack/data/`.
- If a live check fails because of the environment (ports, RAM, network), report it with the output. Don't weaken a
  test to pass.
