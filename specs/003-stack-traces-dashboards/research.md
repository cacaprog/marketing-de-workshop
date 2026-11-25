# Research: Stack Track Phase 3 — Traces and Audit Record

**Feature**: [spec.md](spec.md) · **Plan**: [plan.md](plan.md) · **Date**: 2026-11-25

Each item records a decision, why it was made, and what was rejected. Facts marked *(verified)* were checked on
2026-11-25 against the running stack image (Airflow 3.3.2) or the upstream source of the pinned version.

---

## R1. Where the pipeline spans come from (FR-004)

**Decision**: Turn on **Airflow's native OpenTelemetry traces** (`AIRFLOW__TRACES__OTEL_ON=True`). They are
configured only through the standard `OTEL_*` environment variables (`OTEL_EXPORTER_OTLP_ENDPOINT`,
`OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf`, `OTEL_SERVICE_NAME=airflow`).

*(verified in the image)* Airflow 3.3.2 emits:

- one **`dag_run.aurora_midia_diario`** span per DAG run. The scheduler emits it **when the run ends**, with the
  run's trace and span ids taken from `DagRun.context_carrier`.
- one **`worker.<task_id>`** span per task try (`worker.<task_id>[<map_index>]` for mapped tasks), created in the
  task process as a child of the run's context. Its attributes are `airflow.dag_id`, `airflow.task_id`,
  `airflow.dag_run.run_id`, `airflow.task_instance.try_number` and `map_index`. A task exception sets ERROR
  status. The span is the **current span** while the task body runs.
- `[traces] otel_host/otel_port/otel_service` are deprecated since 3.2 in favor of the standard variables.
  `task_runner_flush_timeout_milliseconds` (default 30000) bounds the flush at task exit.

Because every Cosmos dbt model and test is its own Airflow task, every dbt step also gets a span with its own
duration and status, with no dbt-side instrumentation.

**Alternatives rejected**:
- *A hand-written Airflow listener plugin that emits spans*: it duplicates a built-in feature (Principle VI:
  prefer the tool).
- *dbt-level spans*: dbt-core has no OpenTelemetry output. Task-level spans from Cosmos are enough for the
  Block 4/5 story. Recorded as an honest gap ("sem spans dentro do dbt").

---

## R2. Joining the agent's trace to the run (FR-005, SC-003)

**Decision**: **The same trace.** In the DAG file, `run_stack()` injects the current W3C context (the
`worker.<task>` span) into the subprocess environment as `TRACEPARENT`. On start, the `agentready-stack` CLI
extracts it and **attaches** it as the current context. The shared agent's `tracing.span(...)` calls use
`start_as_current_span`, so `agent.run` becomes a child of `worker.agente.executar` **with no change to
agent code** (Principle I, FR-002).

Consequences:
- `rep.trace_id`, `ops.change_log.trace_id`, `ops.approval_queue.trace_id` and the Marquez facet all carry
  the **run's** trace id. There is still exactly one agent run per DAG run (`max_active_runs=1`, and the ledger),
  so the mapping stays 1:1. In the audit log, `agent.run` now has a `parent_span_id` that isn't in the log.
  `tracing.tree()` already treats that as a root, so `agentready trace <id>` keeps working on the stack's log.
- Approvals and expiries are applied in `aprovacao.aplicar`, inside the same DAG run, so their `human.approval`
  / `human.approval_expired` spans land in the **same trace** (FR-008) with no linking code.
- From the agent's spans to the pipeline spans takes **0 steps**: they are in one trace tree.

**Alternatives rejected**:
- *Separate agent trace plus span links*: two lookups, and Phoenix shows links less prominently than the tree.
- *Deriving the trace id from `dag_run_id`*: re-implements what Airflow's carrier already does.

---

## R3. Domain spans: contracts, observability, ingestion, agent outcome (FR-004, US2 AS2–AS3)

**Decision**: A small **stack-owned tracer** (`agentready_stack/telemetry.py`). It is its **own
`TracerProvider`** (never the global one), exports **OTLP only**, uses `service.name=aurora-stack`, and is
parented by the attached `TRACEPARENT` context. The stack tasks add the spans listed in
[contracts/span-catalog.md](contracts/span-catalog.md):

- `ingestao.parametros`: incident, autonomy override, distribution breaker and its source.
- `contratos.lote`, one per batch evaluated in this run: feed, batch, rows, quarantined rows, rate, limit,
  status, `barred_by`. **ERROR** when the batch is barred, with a pt-BR reason.
- `observabilidade.veredito`, one per pillar × target: status, observed value, baseline, ratio. ERROR on `fail`.
  `warn` stays OK with `agentready.status=histórico insuficiente`.
- `agente.resultado`: `done` / `skipped_duplicate` (explicit, FR-004) and the request ids.
- `fechamento.resumo`: stale sources, pending requests, lineage and trace checks.

**Why a separate provider**: the global provider (set by `tracing.init()`) also writes the **hash-chained audit
log**. Pipeline spans don't belong in the audit record of decisions (FR-011). They would also make the stack's
log differ from the default track's in content.

**Alternative rejected**: *calling `tracing.span()` from the stack tasks*. It mixes pipeline telemetry into the
audit record.

---

## R4. The collector (FR-001, FR-012)

**Decision**: **OpenTelemetry Collector Contrib `0.166.0`** (`otel/opentelemetry-collector-contrib:0.166.0`,
the newest release on 2026-11-25 *(verified on Docker Hub)*), internal to the Compose network with no host port.
Pipeline ([contracts/collector-pipeline.md](contracts/collector-pipeline.md)):

`otlp` receiver (HTTP 4318) → `memory_limiter` → `resource` (upsert `openinference.project.name=aurora`) →
`transform` (OTTL: set `openinference.span.kind` from span names, so Phoenix shows AGENT/TOOL/LLM/CHAIN) →
`batch` → OTLP/HTTP exporter to Phoenix, with a **persistent `sending_queue`** (`file_storage` extension in
`stack/data/otel-queue/`) and `retry_on_failure` (max elapsed 2 h). Extensions: `health_check` (13133) and
`file_storage`.

- If **Phoenix is down**, the collector keeps spans on disk and delivers them when it returns. This satisfies FR-012
  without the run waiting.
- If **the collector is down**, producers fail fast: `OTEL_EXPORTER_OTLP_TIMEOUT` is small and Airflow's flush
  timeout is set to 3000 ms. Those spans miss Phoenix, but **the agent's decisions are still in the audit log**,
  because it is written independently. `fechamento` says so in pt-BR (R6).
- Collector 0.144 renamed the OTLP exporters (new `otlp_grpc` / `otlp_http` names; old names kept as aliases).
  The config uses the name the pinned version documents, and a test runs `otelcol-contrib validate` on it.

**Alternative rejected**: *exporting straight to Phoenix* (it accepts OTLP). That is simpler, but a Phoenix
restart loses pipeline spans. Every producer would need the Phoenix-specific project attribute, and nothing could
set span kinds without touching agent code. Justified in Complexity Tracking.

---

## R5. The trace store: Phoenix (FR-003, FR-006, FR-009, FR-017)

**Decision**: **Arize Phoenix `version-22.0.1-nonroot`** (released 2026-11-21 *(verified)*), stored in a new
`phoenix` database on the **existing `postgres:16`** service. Phoenix requires PostgreSQL ≥ 14. Configuration
*(env names verified in `src/phoenix/config.py` at tag `arize-phoenix-v22.0.1`)*:

| Variable | Value | Why |
|---|---|---|
| `PHOENIX_SQL_DATABASE_URL` | `postgresql://phoenix:phoenix@postgres:5432/phoenix` | persistent until `make reset` (FR-003) |
| `PHOENIX_TELEMETRY_ENABLED` | `false` | no usage telemetry (FR-017) |
| `PHOENIX_ALLOW_EXTERNAL_RESOURCES` | `false` | no web fonts, downloads or price fetches: works offline (FR-017) |
| `PHOENIX_DISABLE_MODEL_COST_AUTO_UPDATE` | `true` | belt and braces for offline |
| `PHOENIX_DISABLE_AGENT_ASSISTANT` | `true` | Phoenix's built-in LLM assistant would need a key and network |
| `PHOENIX_PORT` | `6006` (host `${PHOENIX_PORT:-6006}`) | UI and OTLP/HTTP |
| auth | off (default) | local study only, same as the other UIs; documented |

- **Stable deep links** *(verified in `js/app/src/Routes.tsx`)*: `/redirects/traces/<trace_otel_id>` and
  `/redirects/spans/<span_otel_id>` resolve the project and open the trace. They are used everywhere a link is
  needed (R8).
- **Fallback**: 22.0 is a new major version (2026-11-20). If the spike (quickstart V-P3-0) shows a problem, pin
  `version-21.3.0-nonroot` and record why.
- **Root-span timing risk**: Airflow emits the `dag_run` root span only when the run **ends**, after the approval
  wait. Until then the run's spans have no root in Phoenix. The spike checks how Phoenix lists such a trace. The
  deep link by trace id and the Spans tab filter (`name == "agent.run"`) work either way, and the runbook uses them.

**Alternatives rejected**:
- *Langfuse v3*: it needs ClickHouse, Redis and object storage, which threatens the 8 GB minimum.
- *Jaeger*: light, but it has no agent/LLM view, and the default track's Block 4 exercise already teaches Phoenix.
- *Grafana Tempo + Grafana*: excluded by clarification Q2 (no dashboard tool in Phase 3).

---

## R6. The audit record, and behavior when a component is down (FR-011, FR-012, SC-005, SC-006)

**Decision**:
- **`tracing.py` is not modified.** Its existing `init()` already adds an OTLP `BatchSpanProcessor` when
  `OTEL_EXPORTER_OTLP_ENDPOINT` is set, **next to** the hash-chain `SimpleSpanProcessor`. The stack only sets the
  variable and installs `opentelemetry-exporter-otlp-proto-http` in the agent venv. That is the repository's own
  `otlp` extra, on the same release line as the locked SDK (1.45.x).
- The **hash-chained `stack/data/traces/audit.jsonl` stays the audit record of truth**. It is written
  synchronously, before and regardless of any export. Verification on the stack is `make auditoria`, which runs
  the shared `agentready verify` against the stack's log.
- `agentready-stack` calls `tracing.flush()` before exit, so the BatchSpanProcessor hands the agent's spans to
  the collector.
- `fechamento` checks that the run's trace reached Phoenix, using GraphQL `getTraceByOtelId` with a few retries
  within 30 s (SC-004). If it hasn't, the run still succeeds. It prints a pt-BR warning: *"o trace `<id>` ainda não
  está no Phoenix (…); as decisões estão no log de auditoria — `make auditoria`"*. If the collector is reachable
  but Phoenix isn't, the warning says the spans are queued and will be delivered.

**Honest gap**: the Phoenix copy **is not tamper-evident**. It is a database anyone with access can edit. The
Block 4 point becomes sharper: *explore in Phoenix, prove with the hash chain.*

---

## R7. Trace parity (FR-010, SC-002)

**Decision**: Extend the existing parity harness (`parity.py`). It already runs the same `ReadyAgent("rules")` on
each track in its own subprocess with its own `AGENTREADY_TRACES`. Each side now also returns its
**normalized agent trace**, read from its own audit log (`tracing.load(rep.trace_id)`):

- Kept: span name, tree position (path of names from `agent.run`), status, status message, attributes, event
  names and event attributes.
- Dropped: `trace_id`, `span_id`, `parent_span_id`, `start_time`/`end_time`, `hash`/`prev_hash`.
- Siblings are ordered by `(name, campaign_id attribute)`, not by time.
- Any attribute that legitimately differs (none expected) needs a named rule in `contracts/trace-parity.md`.
  The first run that finds one is a **defect to investigate**, not a normalization to add silently.

The report becomes **2.1.0** (additive `compared.traces`). `compare()` (1.0.0) and `compare_full()` (2.0.0) stay
as they are, so the Phase 1 and 2 tests pass unchanged. The new `compare_all()` produces 2.1.0. A separate **live check** (`make test-live`) compares Phoenix's copy of a real DAG run's agent subtree
with the audit log's copy. It ignores the `openinference.*` attributes the collector adds.

---

## R8. Links from the orchestrator (FR-007, SC-003)

**Decision**: There is one URL builder (`telemetry.trace_url(trace_id)` → `http://localhost:${PHOENIX_PORT}/redirects/traces/<id>`), used in:

1. **The approval form** (`approvals.to_hitl_kwargs`): `[Abrir o raciocínio do agente no Phoenix](…)` next to
   the existing `Trace:` line. It is 1 click from the request to the trace.
2. **The `agente.executar` task log and XCom** (`trace_url`). A skipped run logs *"sem trace: já decidido para
   estes dados"* and the `agente.resultado` span says the same.
3. **`make decisoes`** gains a link column, and **`make traces`** lists the latest runs with business date,
   incident, agent status and link.

**Alternative rejected**: Airflow *operator extra links* on `@task`. They need a custom operator class for each
task and a plugin, which is a lot of code for one link the task log already carries.

---

## R9. Rollback spans (FR-008)

**Decision**: `make rollback CHG=…` calls a new `agentready-stack rollback` instead of `agentready rollback`. It
looks up the change's `trace_id` in `ops.change_log`, opens a stack span `humano.rollback` with a **span link**
to that trace's `agent.run` span (span id read from the audit log) and the attribute
`agentready.original_trace_url`, then calls the **shared** rollback. That writes the usual `human.rollback`
span to the audit log as a child. A rollback happens outside the DAG run, so it is its own trace. It is linked,
not nested.

---

## R10. Host resources (FR-021, SC-007)

**Estimate**: Phoenix with Postgres storage uses ~0.5–0.8 GB, and the collector with `memory_limiter` set to 256 MiB
uses ≤ 0.3 GB. On top of the measured Phase 2 peak of 2.6 GB, that gives ~3.5 GB, well within the **8 GB
minimum, which stays**. The real peak is measured during a full run (`docker stats`) and recorded in the guide.
Images: about +0.6 GB of disk.

---

## R11. Known gaps for "Lacunas conhecidas" (FR-019, Principle VII)

1. The **Phoenix copy isn't tamper-evident**. The hash-chained log is the proof (R6).
2. There are **no spans inside dbt**. Each model or test is an Airflow task span (R1).
3. **Tasks that never start** (upstream failed) have no span. The `dag_run` span ends with the failed state, and
   the orchestrator shows the rest.
4. The **run's root span arrives when the run ends**, after the approval wait. Until then, use the link or the
   Spans tab (R5).
5. **Grafana/dashboards** were removed from the roadmap. Nothing in the stack names a module for them to replace
   (clarification Q2).
6. **`agentready trace` with no id doesn't list the stack's runs**: `agent.run` has a parent (the Airflow task) that
   isn't in the log, and the listing keeps only parentless spans. `make traces` is the listing. `agentready trace <id>`
   still renders the agent tree from the audit log, as the terminal fallback (corrected after the code review).
