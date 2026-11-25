# Implementation Plan: Stack Track Phase 3 — Traces and Audit Record

**Branch**: `003-stack-traces-dashboards` | **Date**: 2026-11-25 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/003-stack-traces-dashboards/spec.md`

## Summary

This closes the last gap the stack guide lists for Block 4: *"Traces e painéis continuam como na trilha padrão
até a Fase 3."* The design rests on one fact verified in the running image: **Airflow 3.3.2 already emits
OpenTelemetry spans** for each DAG run and each task, and the task's span is the current context while the task
body runs ([R1](research.md#r1-where-the-pipeline-spans-come-from-fr-004)). So:

1. **One trace per run.** Turn on Airflow's traces. `run_stack()` passes the task's context to the
   `agentready-stack` subprocess as `TRACEPARENT`, and the CLI attaches it. The shared agent's spans become
   children of `worker.agente.executar` **without touching agent code**. Approvals and expiries run in the same DAG
   run, so they land in the same trace ([R2](research.md#r2-joining-the-agents-trace-to-the-run-fr-005-sc-003)).
2. **Domain spans** from a stack-owned tracer (its own provider, OTLP only, never in the audit log): batches with
   their quarantine and breaker verdicts, the observability verdicts, the agent outcome and the run summary
   ([R3](research.md#r3-domain-spans-contracts-observability-ingestion-agent-outcome-fr-004-us2-as2as3)).
3. **Collector → Phoenix.** The OpenTelemetry Collector (0.166.0) adds the project and span kinds and **queues on
   disk** while Phoenix is down. Phoenix (22.0.1, on the existing Postgres) is the browsable store, with stable
   `/redirects/traces/<id>` links in the approval form, task logs and `make decisoes`
   ([R4](research.md#r4-the-collector-fr-001-fr-012), [R5](research.md#r5-the-trace-store-phoenix-fr-003-fr-006-fr-009-fr-017), [R8](research.md#r8-links-from-the-orchestrator-fr-007-sc-003)).
4. **The audit record doesn't move** (clarification Q1). `tracing.py` is unchanged. Its existing OTLP branch
   exports **alongside** the hash chain, and `make auditoria` verifies the stack's log
   ([R6](research.md#r6-the-audit-record-and-behavior-when-a-component-is-down-fr-011-fr-012-sc-005-sc-006)).

The parity check gains a `traces` comparison (report 2.1.0). No dashboard tool is added (clarification Q2).

## Technical Context

**Language/Version**: Python 3.12 (stack image). The default track is unchanged (≥ 3.11).

**Primary Dependencies**: Airflow 3.3.2 native traces (its image already ships opentelemetry-sdk and the OTLP
exporters 1.44.0); **OpenTelemetry Collector Contrib 0.166.0**; **Arize Phoenix `version-22.0.1-nonroot`**
(fallback 21.3.0, R5); the agent venv adds `opentelemetry-exporter-otlp-proto-http` on the locked SDK's release
line (1.45.x), the repo's existing `otlp` extra. Cosmos 1.16, dbt 1.12, Elementary and Marquez are unchanged.

**Storage**: a new `phoenix` database on the existing `postgres:16`; `stack/data/otel-queue/` (the collector's
persistent queue). The audit log `stack/data/traces/audit.jsonl` is unchanged in format. No new warehouse tables
([data-model.md](data-model.md)).

**Testing**: pytest in the one-off container (`make test`). Span assertions use an in-memory exporter on the stack
tracer, and the collector config is checked with `otelcol-contrib validate`. Trace parity is part of `make parity`.
Live behavior (Phoenix copy == audit copy, outages) runs in `make test-live`. The default suite runs unchanged.

**Target Platform**: Linux/macOS with Docker Compose ≥ 2.14, x86_64 and arm64. The Phoenix and collector images
are multi-arch.

**Project Type**: containerized data pipeline (extends `stack/`).

**Performance Goals**: an agent trace is searchable in Phoenix ≤ 30 s after the agent step (SC-004). Tracing adds
no visible time to a run. A collector outage costs at most a few seconds per task (bounded flush, R4).

**Constraints**: **8 GB free RAM minimum stays** (estimated peak ~3.5 GB, R10); offline after images are pulled
(Phoenix external resources and telemetry off); pt-BR user-facing text; no host port for the collector; no agent
or capability code changes (Principle I).

**Scale/Scope**: +2 services (collector, Phoenix), 1 renamed init service, ~6 span types, 1 new module
(`telemetry.py`), 3 commands (`auditoria`, `traces`, `rollback` wrapper), parity +1 section. The DAG graph is
unchanged.

No NEEDS CLARIFICATION remain: research R1–R11 resolved them. Three facts are left for the spike (quickstart
V-P3-0): Phoenix's listing of a trace with a late root, the OTLP timeout unit, and the exporter component name.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Gate | Pre-research | Post-design |
|---|---|---|---|
| I. Agent is the constant | Same agent source; parity covers decisions | ✅ FR-002 | ✅ `agent.py`, `capabilities.py` and **`tracing.py` are unchanged**. The agent joins the run's trace by context propagation only. Trace parity (R7) proves the span names and attributes are identical across tracks |
| II. Safety in the backend | Text never authorizes; fail-safe; executed changes logged | ✅ | ✅ the audit log is still written synchronously by the shared exporter. No tracing component can block or alter an action. Approvals still re-check live state |
| III. Missing ≠ zero | Blocked/stale never shown as fine | ✅ FR-015 | ✅ barred batches, failed verdicts and stale-data refusals are ERROR spans. Unknown values are omitted, never 0 (span catalog) |
| IV. Deterministic & offline by default | Default track untouched; stack optional | ✅ FR-016/017 | ✅ only `stack/` and the docs change. Phoenix and the collector run offline. Tests disable OTLP export |
| V. One test per promise | Test for each FR-018 promise; parity | ✅ | ✅ test matrix below. Parity extended, not replaced |
| VI. Every tool replaces a module | Replacement map | ✅ | ⚠️ Phoenix replaces `agentready trace` / `render_html` (stack). The **collector** is justified as the routing and buffering point (Complexity Tracking). Airflow's traces are a feature of the orchestrator already in the stack. The hash chain stays (**partial replacement**, Q1) |
| VII. Accurate claims | Gaps documented | ✅ FR-019 | ✅ R11 lists six gaps: Phoenix isn't tamper-evident, no spans inside dbt, late root span, and others. Phoenix 22.0 is described as "versão nova", not "estável há tempo" |

**Result**: PASS with 3 justified items (Complexity Tracking).

### Replacement map additions (go into `stack/README.md`, FR-019)

| Tool | Version | Replaces (default track) | Block |
|---|---|---|---|
| **Airflow traces (OpenTelemetry, nativo)** | 3.3.2 | — (feature of the orchestrator already in the stack): one span per run and per task, so the pipeline joins the agent's trace | 4, 5 |
| **OpenTelemetry Collector** | 0.166.0 | the export point of `tracing.py` (`init()` → a file or a single endpoint): receives agent, pipeline and Airflow spans, adds project and span kinds, **queues while Phoenix is down** | 4 |
| **Arize Phoenix** | 22.0.1 | `agentready trace` (list, terminal tree) and `tracing.render_html()`: search, span tree, attributes and errors in the browser, with links from approvals | 4, 5 |
| *(not replaced, on purpose)* `HashChainJsonlExporter` + `verify_chain()` | — | stays the audit record (`make auditoria`). Phoenix is for exploring, the hash chain is the proof | 4 |

## Project Structure

### Documentation (this feature)

```text
specs/003-stack-traces-dashboards/
├── plan.md              # this file
├── research.md          # R1–R11
├── data-model.md        # run trace, spans, audit record, column meaning, Phoenix, queue, parity item
├── quickstart.md        # V-P3-0 … V-P3-14
├── contracts/
│   ├── span-catalog.md
│   ├── collector-pipeline.md
│   ├── trace-links.md
│   ├── trace-parity.md
│   ├── commands.md                  # Phase 3 delta
│   ├── dag-interface.md             # Phase 3 delta
│   └── parity-report.schema.json    # 2.1.0
└── tasks.md             # /speckit-tasks
```

### Source Code (repository root)

```text
stack/
├── README.md                          # replacement map, gaps (R11), roadmap (Phase 3 ✅, Grafana removed + why), Block 4 runbook, 4 URLs
├── Makefile                           # banner + Phoenix URL; auditoria, traces; rollback → agentready-stack; test + parity set OTEL_EXPORTER_OTLP_ENDPOINT=; reset message
├── compose.yaml                       # + otel-collector, phoenix; marquez-db-init → db-init (all postgres-init/*.sql); telemetry env block
├── config/otel-collector.yaml         # NEW: contracts/collector-pipeline.md
├── postgres-init/02-phoenix.sql       # NEW: idempotent role + database phoenix
├── requirements/agent.in, agent.txt   # + opentelemetry-exporter-otlp-proto-http (same line as the SDK)
├── dags/aurora_midia_diario.py        # run_stack(): inject TRACEPARENT, drop OTEL_SERVICE_NAME; tag stack-fase-3; docstrings
├── scripts/lineage_live_check.py      # + trace checks (Phoenix copy == audit copy; Phoenix and collector outages); maybe renamed live_check.py
├── agentready_stack/src/agentready_stack/
│   ├── telemetry.py                   # NEW: own TracerProvider (OTLP only), attach TRACEPARENT, span helpers, trace_url/span_url, phoenix_has_trace()
│   ├── cli.py                         # attach context at start, flush at exit; + traces, rollback
│   ├── tasks.py                       # spans: ingestao.parametros, contratos.lote, observabilidade.veredito, agente.resultado, fechamento.resumo; trace_url in XCom/log; traces check in close
│   ├── approvals.py                   # Phoenix link in the form body
│   ├── incidents_cli.py               # decisions: trace link column
│   ├── rollback.py                    # NEW: humano.rollback wrapper with span link
│   └── parity.py                      # + normalized agent traces per side; new compare_all() → 2.1.0 (compare_full stays 2.0.0)
└── tests/
    ├── test_telemetry.py              # NEW: TRACEPARENT attach → agent.run parented; stack spans never in audit log; catalog names/attrs/status; unknown ≠ 0
    ├── test_telemetry_config.py       # NEW: collector config validates; compose env/ports; Phoenix offline flags
    ├── test_trace_links.py            # NEW: URL builder; HITL body has link; skip run has no link + reason
    ├── test_rollback_link.py          # NEW: humano.rollback links original agent.run; shared human.rollback in audit log
    ├── test_trace_parity.py           # NEW: normalization (pure) + 2.1.0 schema + identical traces on 'manha'
    └── test_audit_stack.py            # NEW: verify intact/broken on the stack log; agent.run with foreign parent still a root

docs/01-roteiro-do-instrutor.md        # Block 4 (and Block 5 triage) stack-track runbook
docs/02-exercicios.md                  # Block 4: stack variant of exercises 1 and 4 (Phoenix, make auditoria)
```

**Structure Decision**: extend `stack/` as Phases 1–2 did. Nothing outside `stack/` changes except the two
instructor docs. `src/agentready/` is untouched.

### Test matrix (FR-018 promise → test)

| Promise | Test |
|---|---|
| Agent trace reaches the store with the full span tree | `test_telemetry.py` (in-memory, parented tree) + `make test-live` (Phoenix copy == audit copy) |
| Pipeline spans exist and link to the agent trace | `test_telemetry.py` (same trace id under an injected TRACEPARENT) + `test-live` |
| A blocked batch is an ERROR span with the reason | `test_telemetry.py` (`lote_duplicado` fixture → `contratos.lote` ERROR) |
| Failed verdict is ERROR; warn is not | `test_telemetry.py` (`centavos` fixture) |
| Approval/expiry spans in the same trace; rollback links back | `test_telemetry.py` (apply under TRACEPARENT), `test_rollback_link.py` |
| Verify detects tampering on the stack log | `test_audit_stack.py` |
| Run survives a trace-service outage without losing decisions | `test-live` (Phoenix stop/start; collector stop) |
| Agent spans identical across tracks | `test_trace_parity.py` + `make parity` |
| Stack spans never enter the audit record | `test_telemetry.py` |
| Default track unchanged | `uv run pytest -q` (unchanged) |

### Implementation order (for /speckit-tasks)

1. **Spike** V-P3-0 (services + env only). Settle the three open facts.
2. Foundational: `telemetry.py`, CLI attach/flush, `run_stack` TRACEPARENT, test env (`OTEL_EXPORTER_OTLP_ENDPOINT=`).
3. US1: agent subtree in Phoenix, links in the task log and XCom, duplicate-skip span, `make traces`.
4. US2: domain spans, approval link, rollback wrapper.
5. US3: `make auditoria`, outage behavior in `fechamento`, `test-live` additions.
6. Parity 2.1.0.
7. US4: README, instructor script, exercises. Measure RAM (SC-007) and time SC-001.

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|---|---|---|
| OpenTelemetry Collector replaces only the *export point* of `tracing.py`, not a whole module (Principle VI) | FR-012: spans produced while Phoenix is down must not be lost; the persistent queue does that. It is also the one place that sets the project and span kinds without touching agent code (FR-002) | *Export straight to Phoenix*: a Phoenix restart drops the pipeline spans, and each producer would need Phoenix-specific attributes. *Retry in each producer*: blocks task exit, contradicting "a run never waits on the trace service" |
| `db-init` rename (from `marquez-db-init`) | Phoenix needs its own database. One idempotent init service for every `postgres-init/*.sql` beats one service per tool | *A second init service*: duplicates the same psql step for each future tool |
| New service: Arize Phoenix (+1 Postgres database) | FR-006/FR-009: a browsable, searchable trace store with stable links from approvals (FR-007). It replaces `agentready trace` / `render_html()` on the stack | *Keep the terminal tree and static HTML*: no search across runs, no links from the orchestrator, and no pipeline spans. *Langfuse*: needs ClickHouse, Redis and object storage (8 GB minimum at risk). *Jaeger*: no agent/LLM view, and the default track's Block 4 already teaches Phoenix |
| New dependency: `opentelemetry-exporter-otlp-proto-http` in the agent venv | The existing, unchanged `tracing.init()` exports over OTLP only when this package is installed (FR-002) | *Change `tracing.py`* to export some other way: violates Principle I/FR-002. It is already the repo's own `otlp` extra, so nothing new enters the dependency tree |

## Implementation Notes

### Spike V-P3-0 (T007, 2026-11-25)

1. **Collector 0.166.0**: the exporter component is **`otlp_http`** (`otlphttp` was renamed in 0.144). `otelcol-contrib
   validate` passes on `stack/config/otel-collector.yaml`. The image has no shell or curl, so there is no compose
   healthcheck. `fechamento` checks health on :13133.
2. **Phoenix 22.0.1 works (no fallback needed)**, but **auth is on by default** when Phoenix listens on a non-loopback
   address (it does, inside a container). `PHOENIX_ENABLE_AUTH=false` is set explicitly (local study, like the other
   UIs). Without it, both GraphQL and the UI answer 401.
3. **Airflow task processes pick the exporter from `OTEL_TRACES_EXPORTER`** (default `otlp` = **gRPC**). The
   scheduler reads `OTEL_EXPORTER_OTLP_PROTOCOL`. Both are needed: `OTEL_TRACES_EXPORTER=otlp_proto_http` was added
   to compose. Without it, task spans fail with gRPC `UNAVAILABLE` against the HTTP port.
4. **`OTEL_EXPORTER_OTLP_TIMEOUT` is in seconds** in both SDKs in use (1.44.0 in Airflow, 1.45.2 in the agent venv).
   It is set to `"2"`.
5. **Span shape (correction to data-model §1 / span-catalog §A)**: Airflow 3.3.2 emits **three** layers:
   `dag_run.aurora_midia_diario` (root, at run end, ERROR when the run fails) → **`task_run.<task_id>`** (from the
   scheduler, carries the task's **status**, OK/ERROR) → `worker.<task_id>` (task process, the current span while
   the task body runs, status UNSET). Stack and agent spans are children of `worker.*`.
6. **Late root**: during the run, Phoenix counts the trace (`traceCount`) but its root-span listing (the Traces tab)
   doesn't show it until `dag_run.*` arrives at run end. `/redirects/traces/<id>` and the Spans tab work during the
   run. The runbook uses the link from the `agente.executar` log.
7. **Memory (idle, stack up)**: about 2.8 GB total, of which Phoenix uses 437 MiB and the collector 87 MiB. The peak
   during a run is measured in T045.

8. **Refusals aren't error spans (correction to spec US1 AS3)**: the shared agent records a stale-data refusal as
   `sem_dados` in `agent.reasoning` (`decisions`), with `result.stale_campaigns` and `data.stale_sources` on the
   tool spans. It doesn't record an ERROR span, on either track. The spec, data model and quickstart were corrected
   to match. Agent code stays unchanged (Principle I).
9. **Phoenix filter syntax**: Phoenix stores attributes nested, so filters use paths:
   `attributes["airflow"]["dag_run"]["run_id"] == "…"`, `attributes["agentready"]["business_date"] == "…"`.
   GraphQL `spans(first:)` is capped at 1000. Phoenix derives `tool.name` from `gen_ai.tool.name` on ingest
   (ignored by the live comparison, contracts/trace-parity.md).
10. **The Phoenix copy equals the audit copy**: `python -m agentready_stack.trace_check <id>` on a trial-run trace
    gives 8 × 8 spans and 0 differences.

### Validation results (2026-11-25)

- **T014**: `make test` gives 94 + 15 passed (agent venv + DAG integrity; collector config validated). The new Phase 3
  test files gave 41 passed in a separate run, after one test assumption was fixed: a `histórico insuficiente`
  verdict still has a real ratio, so the rule tested is "NULL in the verdict table means the attribute is absent".
  `uv run pytest -q` at the repo root gives 18 passed, unchanged (FR-016).
- **T021 / V-P3-3**: full shadow run `manual__2026-11-25T19:22:37`. It produced one trace with 180 spans:
  `dag_run` → `task_run.*` → `worker.*`; `agent.run` inside `worker.agente.executar` next to `agente.resultado`;
  `contratos.lote` ERROR for the barred batches `ga4-2026-11-23-retry` (100% > 5%) and `ga4-2026-11-05`
  (37.4% > 5%); `observabilidade.veredito` ERROR for ga4 volume (0.0x) and Meta freshness (75 h > SLA 24 h).
  The Phoenix copy of the agent subtree equals the audit copy (8 × 8, 0 differences).
  **V-P3-4**: the second trial run (same data) shows `agente.resultado` `skipped_duplicate` and no `agent.run`.
- **V-P3-11 / SC-002**: `make parity SCENARIO=todos` (report 2.1.0): **0 trace differences in all 7 scenarios**
  (5–8 agent spans each), in 114 s.
- **T045 / SC-007**: the RAM peak during a full run is **3.0 GB** across all containers (scheduler 1.4 GB, Phoenix
  0.44 GB, Marquez 0.40 GB, collector 0.09 GB). That is +0.4 GB over Phase 2, and the 8 GB minimum stays.
- **V-P3-9 / SC-006**: `make auditoria` reported `cadeia íntegra (196 registros)`. After editing the
  `params.new_daily_budget_brl` of one `tool.adjust_campaign_budget` record it exited 1 (broken chain). After
  restoring the file, the chain was intact again.
- **T038/T039 / `make test-live`** (18.9 min, 7 runs in shadow mode): the Phase 2 lineage checks pass (3 tests;
  run B without Marquez is identical). **SC-004**: `agent.run` was in Phoenix by the time the agent task
  finished (0 s measured). (a) Phoenix × audit for run A: 8 × 8 spans, 0 differences. (b) Phoenix stopped
  mid-run: state unchanged, the `fechamento` warning mentions the collector queue, the audit log is intact, and
  the trace arrived 10 s after Phoenix restarted (queue drained). (c) Collector stopped: 155 s → 195 s (≤ +60 s),
  and the decisions are in the audit log. (f) Agent not reached: `agente.executar` is `upstream_failed`, the root
  is ERROR, and there is no `agent.run`. (e) FR-003: after `down` + `make up` the trace of A is still there, and the
  filters by run and by business date find it. **One defect, fixed**: with the collector down and Phoenix up, the
  reason said "o Phoenix responde…" instead of naming the collector. `phoenix_has_trace` now checks the collector
  first (new test), and run E' was re-checked live: `coletor fora do ar…`, decisions in the audit log.
- **T032 (partial)**: V-P3-5 (barred batches as ERROR `contratos.lote` spans) and **V-P3-6** (`centavos`: the
  distribution verdict is ERROR, "R$ 20,229.89 vs mediana R$ 200.4", with `agent.run` in the same trace) pass live.
  **Left for the user**: V-P3-7 (approval link and `human.approval` in the same trace) and V-P3-8 (live rollback
  link). Both need a human approval in Airflow, which the agent must not answer. Unit tests cover both paths
  (`test_trace_links.py`, `test_telemetry.py::test_approval_and_expiry_land_in_the_run_trace`,
  `test_rollback_link.py`).
- **T047 final gate**: `make test` gives **114 + 15 passed** (and `otelcol validate` passes), `uv run pytest -q` gives
  **18 passed**, `make parity SCENARIO=todos` has 0 differences, and `make test-live` passes all Phase 2 and 3 checks
  (after the one fix). **Not done**: the clean-checkout run, which needs the work committed and the running stack
  stopped. It should be done after the commit.
- **T046 (offline, V-P3-13)**: not done. It needs the network disconnected on the host. The configuration
  (`PHOENIX_ALLOW_EXTERNAL_RESOURCES=false`, telemetry off) is in place and tested by `test_telemetry_config.py`.
- **Code review (/ship, 2026-11-25), 4 findings fixed**: (1) the README and research R11 #6 now say that
  `agentready trace` with no id doesn't list the stack's runs (`make traces` does); (2) `phoenix_has_trace`
  requires an `agent.run` span, not just the run's trace; (3) `make test` runs `mkdir -p data/otel-queue` before the
  collector validation, so a fresh checkout doesn't get a root-owned `data/`; (4) the export warnings go to stderr,
  because the last stdout line is the JSON result. Regression tests were added. Left as known edge cases: two
  `agent.run` spans after a retried agent task (the rollback link takes the first), and the trace URL logged when
  export is off.
- **Second code review (/ship), all 10 findings fixed**: trace parity keys stay unique when one tool runs twice on
  the same campaign (`#C03`, `#C03#2`; child paths include the key). With a retried agent task, the latest
  `agent.run` counts (`parity.latest_agent_run`, also used by the rollback link). `telemetry.span` now creates the
  span inside the try (an error there gives an inert span, and the task's own exceptions still propagate). A
  second rollback of the same change is refused and records no span. The Phoenix link is logged only when export is
  on. A NULL `ingested_at` is omitted. Live check: the Phoenix filter is recomputed on each retry for run F; the
  business-date filter is narrowed to `agente.resultado` (the 1000-span cap) and uses run A's own reference date; a
  missing XCom now fails every run except F. Regression tests were added; the affected suites give 63 passed,
  including the Phase 1/2 parity tests unchanged.
