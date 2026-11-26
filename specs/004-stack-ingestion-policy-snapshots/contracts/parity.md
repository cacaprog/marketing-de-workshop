# Contract: Parity report 2.2.0 (delta from 2.1.0)

`make parity [SCENARIO=…]` exits 0 only if **every** section has 0 differences. The existing sections (`gold`,
`source_health`, `decisions`, `verdicts`, `traces`) keep their keys and rules. 2.2.0 adds:

## `compared.bronze`

For each of `bronze.campaigns`, `bronze.ad_spend`, `bronze.conversions`, per `batch_id`: row count and
`bit_xor(hash(row))` over all view columns (dlt columns are already excluded by the view). It also compares the
column set of each table. Differences list `{table, batch_id, field: rows|checksum|columns, default, stack}`.

## `compared.ingestion` (stack side only)

Per source: the load status for the scenario run. Any status other than `carregado` or `sem_dados_novos` is a
difference with its pt-BR reason. With the default failure plan, `ga4.tentativas_http ≥ 1` is expected and not a
difference.

## `compared.policy`

1. Every proposed action in the scenario's agent run: for the stack it's the checks from the span (OPA). For the
   default side it's the checks from its span (local). Ids, verdicts, order and details must be identical. This
   overlaps with `traces` on purpose, so a policy drift is named as such.
2. The `casos.yaml` matrix run through `LocalEvaluator` and through OPA (FR-015a). Differences list
   `{case, check_id, local, opa}`.

## Trace normalization (amends Phase 3 contracts/trace-parity.md)

There is exactly one new ignored key: `policy.evaluator` (`local` vs `opa`), allowed mapping **R7**.
`policy.version` must be equal.

## Stack side procedure (changed)

1. `generate.generate(ref)` with `AGENTREADY_DB=<workdir>/fontes.duckdb`, then the scenario's backfill/incident
   through the shared functions on that store, then the existing `_pin_arrivals` **on that store** (before serving),
   so delivery times match the default side.
2. Start `uvicorn agentready_stack.upstream_app:app --port <free>` with that store. Wait for `/admin/saude`.
3. Ingest all four sources (`falhas_upstream=padrao`) into `ducklake:<workdir>/lake.ducklake`, with ops in
   `<workdir>/ops.duckdb`.
4. `dbt build` (as today), then the agent with `AGENTREADY_POLICY_EVALUATOR=…OpaEvaluator` and
   `OPA_URL=http://opa:8181`.
5. Stop the subprocess. The default side is unchanged.

`parity-report.schema.json` 2.2.0 is generated in the implementation from 2.1.0 plus the three sections above.
