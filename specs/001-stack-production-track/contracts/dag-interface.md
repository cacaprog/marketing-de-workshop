# Interface: DAG `aurora_midia_diario`

The only workflow in Phase 1 (FR-004). Users interact with it through the Airflow UI or the REST
API v2.

## Schedule and run policy

| Property | Value |
|---|---|
| `schedule` | `0 7 * * *` (07:00 in the container's time zone) |
| `catchup` | `False` |
| `max_active_runs` | `1` (FR-007). A run still waiting on an approval holds the next run in the queue; the 20h approval timeout makes unanswered requests expire before the next 07:00 run |
| pool | `duckdb_writer`, 1 slot, for every task that writes to the warehouse |
| `default_args.retries` | `1` (dbt and agent tasks); `0` for approval tasks |
| tags | `workshop`, `bloco-1`, `bloco-4`, `stack-fase-1` |

## Run params (trigger form)

| Param | Type | Default | Effect |
|---|---|---|---|
| `reset_scenario` | bool | `false` | ingest runs `generate.generate()`: a full reset of Bronze and ops state |
| `backfill_meta` | bool | `false` | ingest releases `meta.upstream_backlog` (the same as `agentready backfill-meta`) |
| `incident` | enum `nenhum\|centavos\|renomeacao\|lote_duplicado\|feed_parado\|aleatorio` | `nenhum` | ingest calls `incidents.inject(kind)` |
| `autonomy_override` | enum `manter\|shadow\|supervised\|guarded\|full\|limpar` | `manter` | sets or clears `ops.autonomy_override` before the agent runs |
| `brain` | enum `rules\|claude` | `rules` | the agent's brain. `claude` needs `ANTHROPIC_API_KEY` in the environment |
| `gullible` | bool | `false` | Block 3 simulation: an agent that "believed" the briefing |

## Stages (task groups, in order)

| # | Group / task | Kind | Writes | Notes |
|---|---|---|---|---|
| 1 | `ingestao.preparar` | external_python | bronze, ops, meta | applies the params above; with no params it does nothing (Phase 1 has no live upstream) |
| 2 | `contratos.lint` | bash (dcc venv) | — | `datacontract lint` on every ODCS file (fails the run if one is invalid), then regenerates `_contracts.generated.yml` (never committed) |
| 3 | `contratos.verificar` | Cosmos `DbtTaskGroup` (select `tag:contrato`) | meta, silver, quarantine | `contract_registry` → `contract_checked__*` → `batch_quarantine_rate` → `silver.*`, `quarantine.*`, `meta.batch_status`, plus the Silver contract tests |
| 3a | `contratos.alerta_qualidade` | external_python, leaf | — | **fails** only on *new* blocked batches or schema violations (research R7); nothing downstream depends on it |
| 4 | `gold.construir` | Cosmos `DbtTaskGroup` (select `tag:gold`), `vars={reference_ts}` | gold | `dim_campaign`, `campaign_daily`, `source_health` |
| 5 | `agente.executar` | external_python | ops, traces | ledger check → `ReadyAgent(brain, gullible).run()` → returns the report plus the IDs of the requests it created |
| 6 | `aprovacao.revisar` | `HITLOperator`, mapped per request | — | see `approval-request.md`; nothing is mapped when there are no requests |
| 7 | `aprovacao.aplicar` | external_python, mapped, trigger `all_done` | ops | approve → `capabilities.decide_approval(approve=True)`; reject → `(approve=False)`; expired → `capabilities.expire_approval()` |
| 8 | `fechamento.marca_d_agua` | external_python, upstream `agente.executar` + `aprovacao.aplicar`, trigger `none_failed` (runs even when zero approvals were mapped) | ops | updates `ops.stack_watermark`; writes the run summary as a task note |

## XCom outputs

| Task | Key | Shape |
|---|---|---|
| `agente.executar` | `return_value` | `{status: "done"\|"skipped_duplicate", trace_id, steps:[{kind,text}], requests:[{request_id, action, campaign_id, current, proposed, justification, checks:[{id,passed,detail}], autonomy_reasons:[...]}]}` |
| `aprovacao.revisar[i]` | `return_value` | `{chosen_options:[str], params_input:{}, responded_at, responded_by_user}` (provider payload) |
| `aprovacao.aplicar[i]` | `return_value` | `{request_id, outcome: "executed"\|"rejected"\|"expired"\|"rejected_live_recheck", change_id?, decided_by}` |

## Failure semantics

- If lint fails, stages 3–8 don't run. A contract that can't be read must not be guessed at.
- If a Silver contract test fails, Gold and the agent don't run; the agent never sees unchecked data.
- If the alert fails, nothing else is affected; the run ends `failed`, which is how the UI flags it
  as "needs attention".
- If the agent fails, it retries once. The ledger guarantees no double-apply, and
  `_changes_today` is a second guard.
- An expired approval is recorded as `expired`; the mapped task succeeds (fail-safe is the
  expected outcome, not an error).
