# Contract: Span Catalog (stack track, Phase 3)

Every span name and attribute that tests, the runbook and the parity check rely on. Attribute values are
strings, numbers or booleans. Complex values are JSON strings, following the `tracing._attr` convention.
User-facing messages are pt-BR.

## A. Airflow (native, not ours — listed so tests can rely on them)

| Name | Emitted by | Key attributes | Status |
|---|---|---|---|
| `dag_run.aurora_midia_diario` | scheduler, at run end | `airflow.dag_id`, `airflow.dag_run.run_id`, `airflow.dag_run.*` dates | reflects run state |
| `task_run.<task_id>` | scheduler | `airflow.task_id`, … | **the task's status** (OK/ERROR) |
| `worker.<task_id>` / `worker.<task_id>[<i>]` | task process (child of `task_run.*`) | `airflow.dag_id`, `airflow.task_id`, `airflow.dag_run.run_id`, `airflow.task_instance.try_number`, `airflow.task_instance.map_index` | UNSET (the status is on `task_run.*`, spike finding 5) |

## B. Stack domain spans (`service.name=aurora-stack`, OTLP only, never in the audit log)

Common attributes on every B span: `airflow.dag_run.run_id`, `agentready.business_date` (YYYY-MM-DD,
America/Sao_Paulo), `agentready.incident` (`nenhum` or the type; `aleatorio` stays `aleatorio` so the type isn't
revealed).

| Name | Parent | Attributes | Status |
|---|---|---|---|
| `ingestao.parametros` | `worker.ingestao.preparar` | `agentready.applied` (JSON list, pt-BR), `agentready.reference_ts`, `agentready.breaker.value` (bool), `agentready.breaker.source` (`compartilhado`/`override`), `agentready.autonomy_override` | OK |
| `contratos.lote` (one per batch loaded since the last watermark) | `worker.contratos.alerta_qualidade` | `contract`, `batch_id`, `ingested_at`, `rows`, `quarantined_rows`, `quarantine_rate`, `max_quarantine_rate`, `batch.status` (`passed`/`barred`, the values of `meta.batch_status.status`), `barred_by` (`contrato`/`distribuicao`, absent if passed) | **ERROR** if barred, message: `lote <id> barrado: <motivo>` |
| `observabilidade.veredito` (one per pillar × target) | `worker.observabilidade.resumo` | `pillar`, `target`, `agentready.status` (`pass`/`fail`/`histórico insuficiente`), `observed`, `baseline`, `ratio` (absent when unknown, never 0) | **ERROR** on `fail` (message names feed, batch and ratio). OK on pass and warn |
| `agente.resultado` | `worker.agente.executar` | `agentready.status` (`done`/`skipped_duplicate`), `agentready.request_ids` (JSON), `agentready.trace_url` | OK. For skips the message `sem trace: já decidido para estes dados` is set as an event |
| `fechamento.resumo` | `worker.fechamento.marca_d_agua` | `stale_sources` (JSON), `pending_requests`, `lineage.ok`, `traces.ok`, `traces.reason` | OK (warnings are events, never ERROR: a component outage never fails the run) |
| `humano.decisao` | `worker.aprovacao.aplicar[i]` | `request_id`, `agentready.outcome` (`executed`/`rejected`/`rejected_live_recheck`/`expired`/`already_decided`/`unknown_request`), `decided_by`, `change_id`, `comment`, `agentready.message`. It is the parent of the shared `human.approval` / `human.approval_expired` | OK (added after live validation V-P3-7: the shared code records no span for a rejection) |
| `humano.rollback` | none (own trace) | `change_id`, `actor`, `agentready.original_trace_id`, `agentready.original_trace_url`; **link** → original `agent.run` span | OK / ERROR as the shared rollback returns |

## C. Shared agent and capability spans (unchanged, Principle I)

Names: `agent.run`, `agent.reasoning`, `tool.get_data_health`, `tool.get_campaign_performance`,
`resource.read_policy`, `resource.read_briefing`, `tool.adjust_campaign_budget`, `tool.pause_campaign`,
`human.approval`, `human.approval_expired`, `human.rollback`, `llm.call` (Claude brain only). Attributes are whatever
the shared code sets today. **Phase 3 must not add, remove or rename any of them** (FR-002). The parity check
enforces this (R7).

## D. Collector enrichment (Phoenix copy only)

| Match | `openinference.span.kind` |
|---|---|
| `name == "agent.run"` | `AGENT` |
| name starts with `tool.` | `TOOL` |
| `name == "llm.call"` | `LLM` |
| name starts with `resource.` | `RETRIEVER` |
| everything else | `CHAIN` |

Resource attribute added: `openinference.project.name = "aurora"`.
