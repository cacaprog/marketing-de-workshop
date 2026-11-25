# Data Model: Stack Track Phase 3 — Traces and Audit Record

**Feature**: [spec.md](spec.md) · **Research**: [research.md](research.md)

Phase 3 adds **no warehouse tables**. It changes what one column means, adds one stored artifact (Phoenix's
database), adds an on-disk queue, and defines the shapes below.

## 1. Run trace (one per DAG run)

| Field | Source | Notes |
|---|---|---|
| `trace_id` (32 hex) | Airflow `DagRun.context_carrier` | Every span of the run shares it, including the agent's (R2) |
| root span `dag_run.aurora_midia_diario` | scheduler, emitted **at run end** | attributes `airflow.dag_run.*`; the state shows on the span |
| children `task_run.<task_id>` → `worker.<task_id>[<map>]` | scheduler (`task_run`, carries the task's OK/ERROR status) and the task process (`worker`, current span while the task runs, status UNSET) | one pair per task try (spike finding 5) |
| domain spans | `agentready_stack.telemetry` | catalog: [contracts/span-catalog.md](contracts/span-catalog.md) |
| agent subtree `agent.run → …` | shared `tracing.span` | unchanged names and attributes. Parent = `worker.agente.executar` |
| approval spans `human.approval` / `human.approval_expired` | shared capabilities, run inside `aprovacao.aplicar` | same trace |

**Tree (shape):**

```text
dag_run.aurora_midia_diario
├── task_run.<task> → worker.<task> (one pair per task; shown below by the worker name only)
├── worker.ingestao.preparar ─ ingestao.parametros
├── worker.contratos.lint
├── worker.contratos.verificar.<model>.run / .test …      (Cosmos)
├── worker.contratos.alerta_qualidade ─ contratos.lote × N
├── worker.gold.<model>.run …
├── worker.observabilidade.verificar.<model>.run …
├── worker.observabilidade.resumo ─ observabilidade.veredito × N
├── worker.agente.executar ─┬─ agente.resultado
│                           └─ agent.run ─ agent.reasoning, tool.*, resource.*, (llm.call)
├── worker.aprovacao.revisar[i]
├── worker.aprovacao.aplicar[i] ─ human.approval | human.approval_expired
└── worker.fechamento.marca_d_agua ─ fechamento.resumo
```

## 2. Span (common shape)

`name`, `trace_id`, `span_id`, `parent_span_id`, `start/end`, `status` (`OK` / `ERROR` + message), `attributes`,
`events`, `links`. Resource: `service.name` ∈ {`airflow`, `aurora-stack`, `agente-orcamento-midia`}. The
collector adds `openinference.project.name=aurora` (resource) and `openinference.span.kind` (span) to the
**Phoenix copy only**.

**Status rules (Principle III, FR-015):** on the stack's own spans, a barred batch and a failed verdict are `ERROR`
with a pt-BR message, and a failed task shows ERROR on its `task_run.*` span. The agent's spans are unchanged: a
refusal on stale data is `sem_dados` in `agent.reasoning`, not an error span (implementation finding). "Skipped" is never `OK` with no explanation: it carries
`agentready.status` (`skipped_duplicate`, `histórico insuficiente`). A missing value is never written as `0`. The
attribute is left out, or set to `"null"` (`tracing._attr` convention).

## 3. Audit record (unchanged format)

`stack/data/traces/audit.jsonl`. It is written only by the shared `HashChainJsonlExporter`, so it holds only spans
created through `tracing.span` (agent, capabilities, approvals, rollbacks). Record fields as today: `trace_id`,
`span_id`, `parent_span_id`, `name`, `start_time`, `end_time`, `status`, `status_message`, `attributes`,
`events`, `prev_hash`, `hash`.

- **New fact**: on the stack, the root `agent.run` record has a `parent_span_id`
  (`worker.agente.executar`) that isn't in the file. `tracing.tree()` already treats it as a root.
- Verify result: `(ok: bool, n_records: int, message)`. The message names record *i* and why
  (`elo quebrado` / `conteúdo alterado (<name>)`).
- Pipeline spans (sections 1–2, `aurora-stack` and `airflow`) are **never** in this file (R3).

## 4. Column meaning change

| Column | Before (Phases 1–2) | Now |
|---|---|---|
| `ops.agent_runs.trace_id`, `ops.change_log.trace_id`, `ops.approval_queue.trace_id`, Marquez facet `agentready_trace.trace_id` | trace id of an agent-only trace | trace id of the **DAG run's** trace (contains the agent subtree). Still 1:1 with the agent run |

No migration: old rows keep their old ids, which still resolve in the audit log, and resolve in Phoenix only if
they were exported.

## 5. Phoenix storage

A new Postgres database `phoenix` (role `phoenix`) on the existing `postgres:16` service, created by the
idempotent `stack/postgres-init/02-phoenix.sql`. Project `aurora`. Phoenix's default retention applies (kept until
`make reset`, FR-003). Searchable by: trace id (deep link), span name, and the attributes
`airflow.dag_run.run_id`, `agentready.business_date`, `agentready.incident`, `campaign_id`.

## 6. Collector queue

`stack/data/otel-queue/` (`file_storage`). It holds spans not yet accepted by Phoenix (R4). It is cleared by
`make reset` along with the rest of `stack/data/`.

## 7. Trace parity item (report 2.1.0)

Each side yields a list of normalized spans `[path, status, status_message, attributes, events]`, where `path`
is `agent.run/…/<name>#<campaign_id or ordinal>`. Diffs are `{key: path, field, default_track, stack_track}`. Schema:
[contracts/parity-report.schema.json](contracts/parity-report.schema.json).

## 8. Trace link

`trace_url(trace_id) = http://localhost:${PHOENIX_PORT:-6006}/redirects/traces/<trace_id>`, and
`span_url(span_id)` likewise with `/redirects/spans/`. There is one builder (`telemetry.py`). Consumers are listed
in [contracts/trace-links.md](contracts/trace-links.md).
