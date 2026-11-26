# Contract: Ingestion (dlt) per source

Runs in the `ingest` venv as `agentready-stack task ingest-fonte <fonte> --dag-run-id <id>`. There is one Airflow
task per source.

## Configuration: `stack/ingestion/fontes.yaml`

A declarative dlt REST API source per source:

```yaml
# illustrative shape, not final syntax
ga4:
  client: {base_url: "${UPSTREAM_URL}/ga4/v1", headers: {X-Execucao: "${DAG_RUN_ID}"}}
  paginator: {type: page_number, page_param: page, total_path: null, stop_after_empty_page: true}
  retries: {max: 4, backoff: exponential, respect_retry_after: true}
  resources:
    - name: conversions__ga4
      endpoint: {path: conversoes, params: {page_size: 500}, data_selector: data}
      write_disposition: replace
      columns: {"*": {data_type: text}, ingested_at: {data_type: timestamp, timezone: false}}
```

The `ads` → `ad_spend`, `meta` → `conversions__meta_capi` and `catalogo` → `campaigns` sources follow the same
shape. The destination is dlt's **`filesystem`** (`loader_file_format: parquet`) in a fresh temp bucket, with a fresh
temp `pipelines_dir`, so no dlt state is carried between loads. dlt 1.32.0 can't write a DuckDB 2 lake (`duckdb<2`;
plan Implementation Notes, spike fact 2), so the stack commits the Parquet files into the lake itself (step 5).

## Algorithm (per source)

1. `GET /<fonte>/v1/lotes` → manifest. If the request fails after retries, the load is `falhou` (go to 6).
2. `prev` = the manifest of the last `carregado` row for this source in `ops.ingestion_loads`.
3. If manifest == `prev`, the status is `sem_dados_novos`. Write nothing (go to 6).
4. Run the dlt pipeline into the temp bucket. On any exception (exhausted retries, a page failing mid-way, a load package
   error), the status is `falhou` and the motivo is in pt-BR, e.g. `ga4: fonte indisponível após 4 tentativas (503)`.
   dlt commits nothing.
5. On success, **commit** in one DuckDB 2.0.1 transaction: `CREATE OR REPLACE TABLE warehouse.bronze_raw.<tabela> AS
   SELECT * FROM read_parquet([<the load's files>])`, then recreate the Bronze views, then `COMMIT` (one lake
   snapshot per source load). Any error rolls back, so `bronze_raw` is unchanged and the status is `falhou`. After
   that: `linhas` = rows loaded; `snapshot_id` = current lake snapshot; write an
   `ingestao.<fonte>` checkpoint; status `carregado`; the diff gives `lotes_novos/retirados/inalterados`.
6. Write the `ops.ingestion_loads` row. Emit `ingestao.carga` (ERROR when `falhou`). Print a pt-BR summary line,
   e.g. `ga4: 2 lotes novos, 1 retirado, 4.812 linhas (1 nova tentativa após 503)`. The last stdout line is the JSON
   result.

**Exit code**: 0 for every status, including `falhou`. A source that's down must not stop other sources or the run,
and its feed goes stale (Principle III). Only configuration errors (bad YAML, a missing extension, the lake
unreachable) exit 1.

## Bronze views (recreated after each successful load)

```sql
CREATE OR REPLACE VIEW bronze.ad_spend    AS SELECT * EXCLUDE (_dlt_load_id, _dlt_id) FROM bronze_raw.ad_spend;
CREATE OR REPLACE VIEW bronze.campaigns   AS SELECT * EXCLUDE (_dlt_load_id, _dlt_id) FROM bronze_raw.campaigns;
CREATE OR REPLACE VIEW bronze.conversions AS
  SELECT * EXCLUDE (_dlt_load_id, _dlt_id) FROM bronze_raw.conversions__ga4
  UNION ALL BY NAME
  SELECT * EXCLUDE (_dlt_load_id, _dlt_id) FROM bronze_raw.conversions__meta_capi;
```

The column set of each view equals the default track's Bronze table for the same scenario. Tests and parity check
this.

## Must never

- dedupe, cast, rename, trim or fill business fields;
- write `ingested_at` = load time (it's the source's delivery time);
- commit a partial source;
- call the shared generator (only `upstream` does).
