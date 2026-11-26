# Research: Stack Track Phase 4 — Live Ingestion, Policy as Code and Snapshots

Date: 2026-11-26. Sources are listed per item. Facts marked **(spike)** are confirmed in V-P4-0 before task code
([quickstart.md](quickstart.md)).

## R1. Table format with snapshots (FR-008, Block 5)

**Decision**: **DuckLake** (specification 1.1, the `ducklake` extension that ships with DuckDB 2.0). The catalog
lives in a new `ducklake` database on the stack's existing `postgres:16`. Data files (Parquet) live on a local
volume, `stack/data/lake/`. There is **no object store and no new service**. Parity and the tests use the same
format with a **DuckDB-file catalog** in a temp folder (DuckLake supports both catalog types).

**Rationale**:
- The stack already pins `duckdb==2.0.1` in every venv that opens the warehouse. DuckLake 1.1 and its reference
  extension were released with DuckDB 2.0 (2026-10-21). The `duckdb-core-ext-ducklake` 2.0.0 build is for DuckDB
  2.0.0 (2026-11-09). There is no adapter change: dbt-duckdb attaches a DuckLake catalog through its `attach`
  profile setting (`path: "ducklake:…"`).
- Snapshots are built into the format: `ducklake_snapshots()` lists every commit (id, time, schema version,
  changes), and every table can be read `AT (VERSION => n)` or `AT (TIMESTAMP => t)`. That is exactly the Block 5
  time travel the spec asks for (FR-009).
- Putting the catalog in Postgres makes the "SQL catalog" visible: the audience can see that a lakehouse's
  metadata is just tables. It also lets a reader (`make snapshots`) attach while nobody writes, and it costs no new
  container. The files stay on a host volume that `make reset` clears.

**Alternatives considered**:
- **Apache Iceberg + REST catalog + object store**: it needs a catalog service (Lakekeeper/Polaris) and S3-compatible
  storage. That adds two services and a second write path from dbt-duckdb, which only fully supports Iceberg
  writes through a REST catalog. That is too heavy for the 8 GB minimum and for a workshop.
- **Delta Lake**: DuckDB reads Delta but its write support is limited, and dbt-duckdb doesn't target it.
- **MinIO as file storage**: rejected. The upstream project is in maintenance mode, it stopped publishing
  community Docker images on 2025-10-23, and its community edition is now source-only (MinIO README; Chainguard;
  Docker blog). A local volume is enough, because DuckLake's data path can be any filesystem. If a later phase wants
  object storage, it must pick a store that still publishes community images (Principle VII).

**Sources**: [DuckLake 1.1 release](https://ducklake.select/2026/10/21/ducklake-11/) ·
[DuckLake 1.0 release](https://ducklake.select/2026/04/13/ducklake-10/) ·
[duckdb-core-ext-ducklake 2.0.0](https://pypi.org/project/duckdb-core-ext-ducklake/2.0.0/) ·
[DuckDB docs: DuckLake extension (2.0)](https://duckdb.org/docs/2.0/core_extensions/ducklake.html) ·
[dbt-duckdb](https://pypi.org/project/dbt-duckdb) ·
[MotherDuck: dbt on a local DuckLake](https://motherduck.com/docs/cookbook/dbt-local-ducklake.md) ·
[minio/minio README](https://github.com/minio/minio) ·
[Chainguard on MinIO images](https://www.chainguard.dev/unchained/secure-and-free-minio-chainguard-containers) ·
[Docker blog: MinIO end of life](https://www.docker.com/blog/minio-end-of-life-how-to-stay-patched-and-audit-ready-with-docker-els/)

## R2. Where the operational state lives, and how one connection sees both (FR-011)

**Decision**: data layers go into DuckLake. Operational state stays in a plain DuckDB file, renamed to
**`stack/data/ops.duckdb`**. Each stack connection opens `ops.duckdb` as its main database, so DuckDB names that
catalog **`ops`** after the file stem. The connection then `ATTACH`es the DuckLake catalog as **`warehouse`** and runs
`USE warehouse`. The alias is `warehouse` on purpose: dbt then emits the same OpenLineage dataset names as in
Phase 2 (`warehouse.<schema>.<table>`), so the lineage graph and the Phase 2 tests don't change (the namespace is
confirmed in spike fact 8). This makes the unchanged shared SQL resolve without edits:

| SQL in shared code | Resolves to | Why |
|---|---|---|
| `gold.campaign_daily`, `bronze.*`, `meta.batch_status`, `quarantine.*` | `warehouse.<schema>.<table>` | `warehouse` is the current catalog |
| `ops.campaigns`, `ops.change_log`, `ops.approval_queue`, `ops.agent_runs`, `ops.autonomy_override`, `ops.incidents` | `ops.main.<table>` | there is no `ops` schema in `warehouse`, so DuckDB reads `ops` as a catalog name |

The stack's `warehouse.connect()` (new, in `agentready_stack`) builds this connection, and every stack task already
passes its own connection to the agent (`ReadyAgent(...).run(con)`), to approvals and to rollback. **`db.py` doesn't
change.** The lake must never get an `ops` schema. The stack never calls `db.connect()` (which would create one),
and a test asserts it.

**Rationale**: the live campaign state is OLTP-style data (`ops.campaigns` has a PRIMARY KEY and is updated in
place). DuckLake has no primary or unique keys, and its snapshots must never roll this state back (FR-011,
Principle II). Keeping it in its own file makes the boundary physical: a restore *can't* touch it.

**Alternatives considered**: (a) put `ops` in DuckLake and leave it out of restores. That loses the PK, and a restore
bug could rewind budgets. (b) Generate views in `ops.duckdb` that point at `warehouse.*`. That's two names for every
table and drift whenever dbt adds a model.

**(spike)** Confirm DuckDB 2.0.1's resolution of `ops.campaigns` → catalog `ops` with `USE warehouse` active, including in
`CREATE TABLE IF NOT EXISTS ops.x` (shared `autonomy.py`, `incidents._ensure`) and in dbt-duckdb with
`database: warehouse`. **Fallback**: name the attached file catalog explicitly and run `SET search_path`. If neither
works, the stack connection rewrites nothing and option (b) is used for `ops` only.

## R3. Snapshots, checkpoints, time travel and restore (FR-008–FR-012)

**Decision**:
- **Snapshots come from the format.** Every DuckLake commit (each dlt load, each dbt model) is a snapshot.
- **Checkpoints name them.** The stack writes a row to `ops.lake_checkpoints` at fixed points in a run:
  - each ingestion load (`ingestao.<fonte>`);
  - after the contract stage (`contratos`, recorded by `alerta_qualidade`);
  - after Gold and observability (`gold_observabilidade`, recorded by `observabilidade.resumo`);
  - **right before the agent reads** (`agente`, recorded at the start of `agente.executar`).

  Each row holds the snapshot id (`max(snapshot_id)` from `ducklake_snapshots()`), the run, the stage, the
  batch(es) and the incident open at that moment. Checkpoints live in `ops`, so a restore never erases its own
  index. When the extension supports it, the stack also sets a DuckLake commit message on its own commits
  **(spike)**. That is a convenience; checkpoints are the source of truth.
- **"Gold as of a decision"** (FR-009, SC-005): decision → `ops.agent_runs` (trace id, run) → the `agente`
  checkpoint of that run → `SELECT … FROM gold.campaign_daily AT (VERSION => n)`. One command:
  `make gold-em DECISAO=<trace_id | CHG-… | REQ-…>`.
- **Restore** (FR-010): one transaction over every table in the data-layer schemas (`bronze_raw`, `bronze`,
  `quarantine`, `silver`, `gold`, `meta`, `elementary`). It runs `CREATE OR REPLACE TABLE t AS SELECT * FROM t AT
  (VERSION => n)` for each table, drops tables created after n, recreates tables dropped since n, and recreates the
  Bronze views as of n. The transaction commits as **one new snapshot**, so the later history stays and the restore
  can itself be restored (US2 AS4). It is recorded in `ops.lake_restores` (who, when, from snapshot, to snapshot,
  reason, incident). If DuckLake 1.1 offers a native table rollback, the spike may swap it in, as long as the result
  is still a new snapshot.
- **Guards**: a restore is refused when (a) a DAG run is `queued` or `running` (checked through Airflow's REST API,
  the same instrutor credentials as `make run`), FR-012; (b) the target is older than the last scenario reset
  checkpoint (edge case); (c) the target snapshot doesn't exist or was expired.
- **Incident resolve on the stack** restores to the **last `agente` checkpoint taken before the incident's
  injection** (a complete, consistent set of layers that a clean run produced). Gold and source health then equal
  that clean run exactly (SC-004). The next run re-ingests from the source, which is fixed by then (R6).

**Rationale**: dbt rebuilds tables in many commits, so raw snapshot ids mean little to an audience. Named checkpoints
turn them into "before the agent decided on Tuesday". CTAS-from-`AT` is plain SQL that the audience can read, and it
keeps history append-only.

**Alternatives considered**: restore only Bronze and re-run downstream. That's slower (a full dbt build) and can't
be compared exactly with a known clean state. A per-table restore picked by the user is error-prone on stage.

**Disk**: every run rewrites the table materializations, so files accumulate until snapshots expire. A workshop day
(~50 runs) is estimated at < 1 GB. **(spike)** measures one run. `make reset` clears it all. Snapshot expiry is out
of scope and documented as a gap (R13).

## R4. Mock upstream sources (FR-001, FR-002)

**Decision**: one new service, **`upstream`** (FastAPI on uvicorn, running from the stack image's agent venv). It
plays the role of four source systems under path prefixes: `/ads` (spend), `/ga4` (conversions), `/meta`
(Conversions API) and `/catalogo` (campaign catalog). Its **own state** is a DuckDB file,
`stack/data/upstream/fontes.duckdb`, **written by the shared generator, unchanged**, with `AGENTREADY_DB` pointed at
that file. The generator already writes "what each source has delivered" (with `batch_id` and `ingested_at` = the
delivery time) and `meta.upstream_backlog` (what Meta still holds). The service just serves those tables. Bronze
writing moves from "the generator writes Bronze" to "the generator writes the *sources*, and ingestion fills
Bronze". That is how the spec's assumption ("without changing the default track's behavior") is met. See
[contracts/upstream-api.md](contracts/upstream-api.md).

- **Failures** are deterministic per run (the `X-Execucao` header carries the DAG run id):
  - `falhas_upstream=padrao`: ga4 page 2 answers `503 Retry-After: 1` once per run, so a retry is visible in every
    run's log;
  - `todas`: the first request to every page of every source fails once (SC-003);
  - `nenhuma`.
  - `fonte_fora_do_ar=<fonte>`: that source always answers 503 in the run, so the load fails (edge case).
- **Stalled Meta**: its batch manifest doesn't list the held days, so ingestion sees "no new data". **Backfill**: the
  admin endpoint calls the shared `generate.backfill_meta(con)` on the source store.
- **Admin endpoints** (port 8001, internal network only): reset scenario, backfill, inject/resolve incident, set the failure
  plan. Only the stack's ingestion task calls them.
- **Exposure**: two ports in one process, sharing the store and its lock.
  - **8000** serves the source routes and `/docs`. It is published only as `127.0.0.1:${UPSTREAM_PORT:-8000}`, so
    the instructor can show the OpenAPI page to the audience (Block 1, "é assim que o dado chega") and nothing on
    the network can reach it (FR-020).
  - **8001** serves the admin routes. It is never published: only the stack's tasks reach it, on the compose
    network (`UPSTREAM_ADMIN_URL`). Admin routes don't exist on 8000, so hiding them from `/docs` isn't needed.

**Rationale**: running the shared generator inside the source keeps one source of truth for the scenario (Principle
I, constitution "Shared sources"). FastAPI's automatic `/docs` page shows the source contract live. Starlette and
uvicorn are already in the agent venv (mcp 2.x depends on them), so the only new package is `fastapi`.

**Alternatives considered**: (a) static JSON files. They can't fail, retry or page. (b) Mock with WireMock or
Prism. That needs a second copy of the scenario data, which violates the shared-sources rule. (c) Plain Starlette
with no FastAPI. It saves one dependency but loses `/docs`, which is the part the audience sees.

## R5. Declarative ingestion with dlt (FR-003–FR-005, FR-007)

**Decision** (amended by spike fact 2): **dlt** with its declarative **REST API source** (paginator, retries and
per-resource config in one dict per source, `stack/ingestion/fontes.yaml`), loading to dlt's **`filesystem`
destination as Parquet** in a temp folder. The stack then **commits** the files into `warehouse.bronze_raw` with
DuckDB 2.0.1 in one transaction. dlt 1.32.0 declares `duckdb<2` for its DuckLake destination, so it can't write
the stack's DuckDB 2 lake directly. All of this runs in a new isolated **`ingest`** venv (`dlt[parquet]==1.32.0`,
`duckdb==2.0.1`). One Airflow task runs per source, so one failing source never hides another (edge case).

How each requirement is met:
- **Change detection, then full sync of that source.** Each task first reads the source's batch manifest
  (`GET /<fonte>/v1/lotes`). If it equals the last successful load's manifest (`ops.ingestion_loads`), the status
  is `sem_dados_novos` and nothing is written (no snapshot, edge case). Otherwise dlt loads the source's full
  current content with `write_disposition="replace"` into `bronze_raw.<tabela>`. The per-batch statuses (`novo`,
  `retirado`, `inalterado`) come from the manifest diff (FR-003).
  - *Why replace, not incremental append*: sources in this scenario **withdraw and replace** batches (`centavos` and
    `renomeacao` replace yesterday's ga4 batch; `feed_parado` withdraws it). Bronze must mirror the source exactly,
    or the stack would keep the original **and** the cents batch, so the contract would bar it by duplicate keys
    and the Block 5 lesson (the contract *passes* `centavos`) would vanish. Replace keeps Bronze == source == the
    default track's Bronze. The dataset is tiny (~30k rows), so a full sync takes seconds. The guide says
    incremental cursors are the production default, and why this scenario uses change detection plus replace.
- **No repair of business data** (FR-004): every field is served as text and hinted `data_type: text` (Bronze is
  all VARCHAR, as today). `ingested_at` is hinted `timestamp` with `timezone: false` **(spike)**. Schema evolution
  stays on, so `renomeacao`'s new `utm_campaign` column appears as it does today. Nothing dedupes. A `-retry` or
  `-redelivery` batch is a distinct `batch_id` from the source.
- **Retries never duplicate** (FR-004, SC-003): HTTP retries happen inside dlt's REST client (backoff, honoring
  `Retry-After`). A load package commits atomically, so a source that fails mid-pagination leaves `bronze_raw`
  unchanged (edge cases).
- **No dlt state carried between loads**: each load uses a fresh temp bucket and `pipelines_dir`. With replace
  semantics, Bronze is exactly what the source sent in this load. For example, after `renomeacao` is resolved, the
  `utm_campaign` column disappears on the next load (spike fact 3).
- **Bronze keeps its names and shape**: `bronze.campaigns`, `bronze.ad_spend` and `bronze.conversions` become views
  over `bronze_raw`. They exclude `_dlt_load_id` and `_dlt_id`. `bronze.conversions` is
  `conversions__ga4 UNION ALL BY NAME conversions__meta_capi`. dbt sources, the contract stage, the schema pillar
  (`obs_esquema` compares physical columns) and parity see exactly today's columns. The views are recreated after
  each load.
- **Delivery time is the scenario's**: `ingested_at` comes from the source (the delivery time the generator
  assigned), not from the moment dlt ran. Freshness and SLAs therefore match the default track ("Ingestion run
  times" assumption).
- **Telemetry** (FR-020): dlt sends anonymous telemetry by default. `RUNTIME__DLTHUB_TELEMETRY=false` in the
  environment and `runtime.dlthub_telemetry: false` in the pipeline config turn it off.
- **Lineage** (FR-007): each per-source task declares an inlet asset for its source (`fonte://ga4/conversions`, …)
  and outlets for its `bronze_raw` table and the Bronze view. The Phase 2 OpenLineage provider then emits one node
  per source upstream of Bronze. dlt doesn't emit OpenLineage itself, which the guide documents honestly.

**Alternatives considered**: dlt's `ducklake` or `duckdb` destination (blocked: `duckdb<2`, and dlt 1.31 breaks on
DuckDB 2.0's removed `Relation.fetchone()`). A DuckDB 1.x ingest venv writing the lake (it can't share `ops.duckdb`,
and it mixes DuckLake spec versions on one catalog). Airbyte/Meltano
are a service plus connectors each, far too heavy. Hand-written `requests` loops are what this phase replaces, and
they would hide the declarative idea.

**Sources**: [dlt on PyPI (1.32.0, `duckdb<2`)](https://pypi.org/project/dlt/) · [dlt DuckLake destination](https://dlthub.com/docs/dlt-ecosystem/destinations/ducklake) ·
[dlt 1.13–1.14 release notes](https://dlthub.com/docs/release-notes/1.13-1.14). **(spike)** pins the latest dlt 1.x
that accepts `duckdb==2.0.1`.

## R6. Incidents at the source (FR-006)

**Decision**:
- **Inject.** The `ingestao.parametros` task calls `POST /admin/incidentes {tipo}` on `upstream`. That runs the
  **shared `incidents.inject(con)` on the source store** (no copy). It then mirrors the returned row
  (`incident_id`, kind, injected_at, batch) into the stack's own `ops.incidents`, which is the incident log TTD/TTR
  is computed from. The same run's ingestion brings the change into Bronze.
- **Detect.** `make incidente-detectar` updates `ops.incidents`, as today.
- **Resolve** (`make incidente ACAO=resolver`) does, in order:
  1. `POST /admin/incidentes/resolver`, so the source rolls back (the shared `incidents.resolve` on the source
     store);
  2. a lake **restore** to the last `agente` checkpoint before `injected_at` (R3);
  3. TTD/TTR closed in `ops.incidents`.

  SC-004 counts this as one command. A second command, `make run`, re-ingests from the fixed source.

**Parity of Bronze**: on the default track, `inject` edits Bronze in place. On the stack, the edited source is
synced into Bronze by replace. Both end with the same rows (`renomeacao` included: the ga4 rows of the renamed batch
are served without `campaign_id` and with `utm_campaign`). Parity gains a Bronze comparison (R10).

**Rationale**: the incident is now something that happens *outside*, as in real life. The recovery shows the two
halves of a real fix: the producer fixes the feed, and the data platform rewinds to a known-good version.

## R7. The policy evaluator (FR-013–FR-018, clarification Q1 = A)

**Decision**: a new shared module, `src/agentready/policy.py`, plus one structural change in `capabilities.py`:

- `capabilities._common_checks` and `budget_checks` keep **reading the live state exactly as today** (campaign row,
  `gold.source_health` freshness, other active budgets, changes today). They package those values as **facts**
  (`policy.Fatos`) and call `policy.evaluate(action, facts) -> list[Check]`. The facts are the campaign status,
  human lock, objective, conversion source, freshness status and age, old and new budget, portfolio sum without the
  campaign, changes today, and the justification. The `Check` ids, order, `passed` and `detail` stay the same, and
  the rest of `_gate` and `_execute_approved` don't change. So the decision flow and the agent's rules are unchanged
  (Principle I).
- `policy.LocalEvaluator` holds today's comparisons **moved verbatim** from `capabilities.py`, reading
  `config/guardrails.yaml`. It is the default and needs no network, keeping the default track offline (Principle
  IV).
- **The evaluator is chosen by `AGENTREADY_POLICY_EVALUATOR`** (`module:Class`). It is unset on the default track.
  The stack sets `agentready_stack.policy_opa:OpaEvaluator`, so the OPA client code lives in `stack/`, and the
  default track gains no dependency.
- **Verdicts vs. wording**: OPA returns, per check, the `id`, `passed` and the numbers it compared. The pt-BR
  `detail` text is built by one shared formatter, `policy.describe(check_id, facts, limits)`, which both evaluators
  use. This keeps details byte-identical (FR-014). Number formatting such as `R$ 4.000,00` and `+10%` isn't
  something Rego should own. The *decision* is OPA's; the *sentence* is shared presentation.
- **Fail closed** (FR-016): if OPA can't be reached within 2 s, answers non-200, or the result fails schema
  validation, the evaluator returns one failing check, `politica_avaliada`, with the detail `não foi possível avaliar
  a política: <motivo>`. `_gate` rejects the action, and nothing executes. Read-only capabilities never call the
  policy.
- **Trace attributes**: the shared action span gains `policy.evaluator` (`local` | `opa`) and `policy.version`. On
  the stack the version comes from the policy bundle; locally it is the same version string, read from the policy
  manifest file. Trace parity normalizes `policy.evaluator`, the one allowed difference, recorded as R7 in
  [contracts/parity.md](contracts/parity.md). `policy.version` must be equal.

**Rationale**: this is the user's Option A. The rules exist in two forms, Python and Rego, and the equivalence check
keeps them equal (R8, FR-015a). Detail strings stay shared so traces stay identical across tracks.

**Alternatives considered**: Rego builds the detail strings with `sprintf`. Locale formatting would drift from
Python's, and every drift would be a trace-parity failure. OPA embedded as Wasm in Python adds a Wasm runtime to the
default track (Principle IV).

## R8. OPA deployment and tests (FR-013, FR-015a, FR-017, FR-018)

**Decision**:
- **Service**: `openpolicyagent/opa:<1.x>-static` as service `opa`, internal network only. **v1.21.0 is the newest
  release found; (spike)** confirms it and pins it. It runs `run --server --disable-telemetry --addr :8181` with:
  - the policy, `stack/policy/guardrails.rego` (package `agentready.guardrails`, `version := "1.0.0"`);
  - the limits, **the shared `config/guardrails.yaml` loaded as data** under `data.guardrails` (OPA's
    `prefix:path` loading, **(spike)**). The limits are never copied (FR-013).
- **Decision API**: `POST /v1/data/agentready/guardrails/decisao` with `{"input": {"acao", "fatos"}}` returns
  `{"permitido": bool, "checagens": [{"id", "ok", "valores"}], "versao"}`. See
  [contracts/policy-interface.md](contracts/policy-interface.md).
- **Policy tests**: `stack/policy/casos.yaml` is **one list of cases** (name, action, facts, failed ids expected). It
  feeds both:
  - `opa test` (`guardrails_test.rego` iterates `data.casos` and checks each case's verdict);
  - the pytest equivalence test, which runs `LocalEvaluator` on every case and compares it with OPA's answer
    (FR-015a).

  Every guardrail has ≥ 1 allow and ≥ 1 deny case (FR-018, SC-006). A mutation test copies `guardrails.yaml`,
  changes each limit in turn and asserts that ≥ 1 case fails (SC-006). `make test` runs `opa test` in the `opa`
  image (`docker compose run --rm opa test …`).
- **Ask without running the agent** (FR-017): `make politica ACAO='ajustar C01 5200'`. It builds the same facts from
  the live state (shared code), asks OPA, and prints the checks.

**Rationale**: OPA is the policy engine named in the roadmap, and it is a small static binary (tens of MB of RAM).
Loading the YAML as data keeps `config/guardrails.yaml` the single source of the limits. One case file for both
evaluators is what makes the equivalence claim cheap to keep true.

**Sources**: [OPA releases](https://github.com/open-policy-agent/opa/releases) ·
[OPA v1.21.0 notes](https://newreleases.io/project/github/open-policy-agent/opa/release/v1.21.0)

## R9. dbt, Elementary and DuckDB extensions on DuckLake (FR-008, FR-020)

**Decision**:
- **dbt profile**: `path: /opt/stack-data/ops.duckdb`, an `attach` entry for the lake (alias `warehouse`, Postgres
  catalog, `data_path: /opt/stack-data/lake/`), and `database: warehouse`. Every model materializes into the lake. The
  `elementary` profile is the same, with `schema: elementary`. **(spike)**: dbt-duckdb Python models
  (`contract_checked__*`, `source_health`, `obs_esquema`) and Elementary's incremental tables work on DuckLake. **If
  Elementary fails**, its schema stays in `ops.duckdb` (`elementary` models get `database: ops`), which the guide
  documents as a partial replacement.
- **Offline extensions**: the `ducklake` and `postgres` extensions are installed **at image build** into
  `/opt/duckdb-extensions` for DuckDB 2.0.1. Every connection (stack `warehouse.connect()`, the dbt profile
  `settings`, the dlt destination) sets `extension_directory` to that folder and `autoinstall_known_extensions=false`.
  A missing extension then fails loudly instead of trying the network.
- **information_schema**: queries that list Bronze columns (`obs_esquema`, `tasks._bronze_ready`) filter by
  `table_catalog = 'warehouse'` when the stack runs. This only matters if both catalogs ever share a schema name, which
  the R2 test forbids.

## R10. Parity (FR-005, FR-015a, FR-022)

**Decision**: report **2.2.0** adds three sections:
1. `compared.bronze`: per table, row count and an order-independent checksum of all columns except dlt metadata,
   per batch. Bronze from the source equals the default track's Bronze (SC-002).
2. `compared.policy`: every action proposed in the scenario's agent run, with check ids, verdicts and details from
   both evaluators, plus the `casos.yaml` matrix run through both (FR-015a, SC-006a).
3. `compared.ingestion`: per source, the load status, with no `falhou` expected.

The stack side of parity now:
- generates the **source store** in the workdir with the shared generator;
- starts `upstream` as a subprocess on `127.0.0.1:<free port>`;
- ingests with dlt into a **DuckDB-file DuckLake catalog** in the workdir;
- builds with dbt;
- runs the agent with `OpaEvaluator` pointed at the running `opa` service.

The default side is unchanged. Existing sections (Gold, health, decisions, verdicts, traces) keep their rules. The
trace normalization adds exactly one key, `policy.evaluator`.

## R11. Telemetry (Phase 3 continuity)

New stack spans, documented in the span catalog delta in [contracts/dag-interface.md](contracts/dag-interface.md):
- `ingestao.carga` (per source: status, batches new/withdrawn/unchanged, rows, HTTP retries; ERROR on `falhou`);
- `lake.checkpoint`;
- `lake.restauracao` (from/to snapshot; ERROR when refused);
- `politica.indisponivel` event on the agent task when fail-closed happened.

The agent's spans are unchanged except for the two shared `policy.*` attributes (R7). Stack spans never enter the
audit log (Phase 3 rule).

## R12. Resources, versions and services

| Item | Version / choice | RAM (est.) |
|---|---|---|
| DuckDB / `ducklake` ext. | 2.0.1 / spec 1.1 (bundled with 2.0) | in-process |
| `upstream` (FastAPI + uvicorn, agent venv) | FastAPI latest 0.x pinned in lock | ~120 MB |
| `opa` | **1.22.4** static (spike; latest release 2026-11-12) | ~12 MB idle |
| dlt (`ingest` venv) | **1.32.0** `[parquet]` + pyarrow 26.0.1 + duckdb 2.0.1 (spike) | per task, ~200 MB peak |
| Postgres | existing; + `ducklake` database | +~20 MB |

Estimated peak: Phase 3's 3.0 GB + ~0.4 GB = **~3.4 GB**. The 8 GB minimum stays (FR-025). The disk use per run is
measured in the spike and recorded in the guide.

## R13. Honest gaps (Principle VII, FR-023)

1. **Operational state isn't in the lake** (partial replacement of the single file): budgets, change log, approvals
   and ledger stay in `ops.duckdb`. That's on purpose: a time travel must never rewind money decisions; rollback
   of those goes through the change log.
2. **Full sync, not incremental**: change detection plus replace per source (R5). The guide explains why, and that
   cursors are the production default.
3. **dlt emits no lineage of its own**: the source nodes come from the DAG's declared assets.
4. **Snapshot expiry isn't automated**: files grow until `make reset`. The guide records the disk per run.
5. **Rules exist in two forms** (Python and Rego). They're kept equal by the equivalence check, and any difference
   fails `make test` and `make parity`.
6. **The detail sentence is shared Python**: OPA decides; the pt-BR wording is formatted outside Rego.
7. **DuckLake 1.1 is recent** (October 2026): "versão nova", not "consolidada". Marquez and other tools don't
   render DuckLake snapshots.
8. **The mock sources are a simulation**: deterministic failures, no auth, no rate-limit quotas; only the
   scripted 503s.
9. **An empty `meta.incident_backup` exists in the lake**: the shared `incidents._ensure` creates it when the stack
   creates `ops.incidents`. The stack never uses it (restores replace the backup). It's left alone because shared
   code creates it.
10. **dlt doesn't write the lake itself** (yet): dlt 1.32.0 requires DuckDB < 2, so dlt loads Parquet and the stack
   commits it into DuckLake in one transaction. When dlt supports DuckDB 2, its `ducklake` destination replaces the
   commit step.
