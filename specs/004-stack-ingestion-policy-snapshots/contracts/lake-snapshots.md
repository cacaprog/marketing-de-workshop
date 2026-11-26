# Contract: Lake connection, checkpoints, time travel and restore

## Connection (`agentready_stack.warehouse.connect(read_only=False)`)

1. `duckdb.connect($AGENTREADY_DB)` with `AGENTREADY_DB=/opt/stack-data/ops.duckdb`, so the main catalog is `ops`.
2. `SET extension_directory='/opt/duckdb-extensions'`, `SET autoinstall_known_extensions=false`,
   `SET autoload_known_extensions=true`.
3. `ATTACH 'ducklake:$STACK_LAKE_CATALOG' AS warehouse (DATA_PATH '$STACK_LAKE_DATA')`. The live stack uses
   `postgres:dbname=ducklake host=postgres user=ducklake password=…`; parity and tests use a `.ducklake` file in
   the workdir.
4. `USE warehouse`.

dbt's profile does the same through `path` + `attach` + `database: warehouse`. Every stack command and task uses this
function; none uses `agentready.db.connect()`.

## Checkpoints

`lake.checkpoint(con, etapa, dag_run_id=None) -> CK-…` inserts into `ops.lake_checkpoints` with
`snapshot_id = (SELECT max(snapshot_id) FROM ducklake_snapshots('warehouse'))` and the open incident. It's called at:

| Etapa | Where |
|---|---|
| `reset` | `parametros`, after a scenario reset |
| `ingestao.<fonte>` | end of each `carregado` load |
| `contratos` | start of `contratos.alerta_qualidade`, **pinned to the last snapshot that wrote `meta.batch_status`** (the leaf can run late under the single-writer pool, after Gold) |
| `gold_observabilidade` | start of `observabilidade.resumo` (only inside a DAG run; `make observe` records nothing) |
| `agente` | start of `agente.executar`, **before** the agent reads |
| `restauracao` | after a restore commits |

## Commands

| Command | Output |
|---|---|
| `agentready-stack snapshots [--limit 30]` | pt-BR table: snapshot, time (local), stage label (checkpoint or "(sem marca) após <etapa>"), run, open incident, tables changed. Last line JSON |
| `agentready-stack gold-em <trace_id \| CHG-… \| REQ-…>` | resolves the decision → `agente` checkpoint (data-model §5). Prints the run, snapshot, the Gold rows for the decision's campaign over the lookback window, and the metric the decision cited next to it (from the change/approval params and the audit record). Exit 1 if not found |
| `agentready-stack consultar-em <schema.tabela> <snapshot \| AAAA-MM-DDTHH:MM> [--filtro SQL] [--limite 20]` | read-only query of any data-layer table `AT (VERSION => n)` or `AT (TIMESTAMP => t)` (FR-009). pt-BR table, last line JSON. Refuses `ops.*` (exit 2) and unknown tables (exit 1) |
| `agentready-stack restaurar <snapshot \| CK-…> [--motivo T] [--por ATOR]` | restore (below). Prints `de → para`, the new snapshot, and the undo hint `make restaurar PARA=<de>` |

## Restore algorithm

Pre-checks (each refusal is pt-BR, exit 2, with a `lake.restauracao` ERROR span):
1. No `queued`/`running` run of `aurora_midia_diario` (Airflow REST API).
2. The target exists in `ducklake_snapshots` and is ≥ the latest `reset` checkpoint.
3. The target ≠ the current snapshot.
4. The target contains `gold.campaign_daily`, i.e. complete layers. A `reset` or ingestion-only checkpoint would
   leave the lake empty or half built (found by `make test-live`, 2026-11-26).

Then, in **one transaction** over the schemas `bronze_raw, quarantine, silver, gold, meta, elementary` (never
`ops`):
- for each table that exists at the target: `CREATE OR REPLACE TABLE s.t AS SELECT * FROM s.t AT (VERSION => n)`;
- for each table that exists now but not at the target: `DROP TABLE`;
- `bronze.*` are ordinary tables in the schema list, so the CTAS step restores them like any other table.

Commit → `novo_snapshot`. Insert into `ops.lake_restores`, add a `restauracao` checkpoint, and emit the
`lake.restauracao` span. **Post-condition**: every data table read at `novo_snapshot` equals its read at `n`, and the
`ops` tables are byte-identical before and after (tested).

## Incident resolve (`agentready-stack incident resolve`)

1. Find the open incident in `ops.incidents`, or fail with `nenhum incidente aberto`.
2. `POST upstream /admin/incidentes/resolver`.
3. Target = the latest `agente` checkpoint with `criado_em < injected_at`. If none exists, the latest
   `gold_observabilidade` checkpoint before `injected_at` (complete layers), with a pt-BR warning. If neither exists
   (e.g. the incident came with a scenario reset), **nothing is restored**: the incident still closes, with a
   warning that the next run reloads the corrected batch from the source.
4. Restore (above), with `motivo = "incidente <id> resolvido"`.
5. Set `detected_at` (if NULL) and `resolved_at` in `ops.incidents`, and print TTD/TTR (`incidents.metrics`).
