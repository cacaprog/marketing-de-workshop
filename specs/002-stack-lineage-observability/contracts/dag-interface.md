# Interface: DAG `aurora_midia_diario`, Phase 2 changes

This extends [Phase 1's DAG interface](../../001-stack-production-track/contracts/dag-interface.md). Anything not
listed here is unchanged.

## Run params (added)

| Param | Type | Default | Effect |
|---|---|---|---|
| `disjuntor_distribuicao` | enum `compartilhado\|ligado\|desligado` | `compartilhado` | the effective distribution breaker for **this run only** (FR-005). `compartilhado` reads `config/guardrails.yaml` → `observability.block_on_distribution_anomaly` |

The parity check ignores this param (it always uses the shared file).

## Stages (new rows marked ★)

| # | Group / task | Kind | Writes | Notes |
|---|---|---|---|---|
| 1 | `ingestao.preparar` | as Phase 1 | + `ops.stack_run_settings` | also resolves the breaker → XCom `{"breaker": {"value": bool, "source": "compartilhado"\|"override"}, "min_history": int}` and logs it in pt-BR |
| 3 | `contratos.verificar` | Cosmos, `tag:contrato`, `vars={block_on_distribution_anomaly, min_history}` | + `meta.distribution_by_batch` | the breaker lives here (research R3): `batch_status.barred_by`, quarantine reason, Silver filter |
| 3a | `contratos.alerta_qualidade` | unchanged | — | it now also fires for **new** batches with `barred_by='distribuicao'` |
| 4 | `gold` | unchanged | gold | |
| 5★ | `observabilidade.verificar` | Cosmos, `tag:observabilidade`, `vars={reference_ts, min_history}`, `TestBehavior.NONE` | `meta.observability_checks` | the four `obs_*` models and their union only (no tests here, so a failed verdict never blocks the agent) |
| 5c★ | `observabilidade.testes` | `DbtTestLocalOperator`, `select=tag:observabilidade`, **leaf**, `retries=0` | `elementary.*` via hooks | `observability_check_passes` tests (`severity: error`): a failed verdict is **red** in Airflow and in the Elementary report |
| 5a★ | `observabilidade.resumo` | `@task` → `agentready-stack task observe`, **leaf**, `retries=0` | — | prints the pt-BR five-pillar table; **fails** (`ObservabilityAlert`) when any verdict is `fail`; XCom = list of verdicts |
| 5b★ | `observabilidade.relatorio` | `@task` → `edr report` (dbt venv), pool `duckdb_writer`, leaf | `stack/data/elementary/index.html` | rebuilds the web report; on error it logs `relatório de observabilidade não atualizado: …` and **succeeds** (edge case) |
| 6 | `agente.executar` | as Phase 1, upstream now `observabilidade.verificar` | ops, traces | sends the `agentready_trace` run facet (R4) |
| 9 | `fechamento.marca_d_agua` | as Phase 1 | ops | also checks the lineage store and logs `linhagem indisponível: …` if it's down (never fails for that) |

Order: `ingestao` → `contratos.lint` → `contratos.verificar` → `gold` → `observabilidade.verificar` →
`agente` → `aprovacao` → `fechamento`. The leaves are `contratos.alerta_qualidade`, `observabilidade.testes`,
`observabilidade.resumo` and `observabilidade.relatorio`. `observabilidade.verificar` → `[testes, resumo]`;
`testes` → `relatorio` (`trigger_rule=all_done`, so the report always includes this run's results).

## Inlets / outlets (lineage for Python tasks, FR-009/FR-010)

Declared as OpenLineage `Dataset(namespace="duckdb:///opt/stack-data/warehouse.duckdb",
name="warehouse.<schema>.<table>")` objects. The provider passes them through unchanged
(`ExtractorManager.convert_to_ol_dataset`), and these are the same names Cosmos/dbt emit. Airflow `Asset`s with a
`duckdb://` URI were not used: the provider has no converter for that scheme, so they would be dropped.

| Task | Inlets | Outlets |
|---|---|---|
| `ingestao.preparar` | — | `bronze.campaigns`, `bronze.ad_spend`, `bronze.conversions` |
| `observabilidade.resumo` | `meta.observability_checks` | — |
| `agente.executar` | `gold.campaign_daily`, `gold.source_health`, `meta.batch_status` | `ops.change_log`, `ops.approval_queue`, `ops.campaigns` |
| `aprovacao.aplicar` | `ops.approval_queue`, `ops.campaigns` | `ops.change_log`, `ops.campaigns` |

## Failure semantics (added)

- If an `obs_*` **model** errors (it can't compute), the agent doesn't run: the default trigger rule fails safe
  (FR-008). A **verdict** of `fail` doesn't stop the agent. It fails the `resumo` leaf, which marks the run as
  needing attention (US1 AS2).
- With the breaker on, a batch barred by distribution never reaches Silver, Gold or the agent (FR-005,
  SC-002).
- A Marquez outage never changes task states or decisions (FR-013).

## Tags

`stack-fase-1` → `stack-fase-2`, plus `bloco-5`.
