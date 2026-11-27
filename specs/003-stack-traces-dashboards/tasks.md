---

description: "Task list for Stack Track Phase 3 (traces and audit record)"
---

# Tasks: Stack Track Phase 3 — Traces and Audit Record

**Input**: Design documents from `/specs/003-stack-traces-dashboards/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md

**Tests**: REQUIRED. FR-018 and constitution Principle V ask for one automated test per Phase 3 promise
(plan.md → "Test matrix"). In each story, write the tests first and confirm they fail before implementing.

**Organization**: tasks are grouped by user story (spec.md US1–US4). Phase 1 is a **spike gate**: three facts the
plan leaves open (research R4/R5) must be settled before any task code is written.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel (different files, no dependency on an unfinished task)
- **[Story]**: US1–US4 from spec.md
- All paths are relative to the repo root. Everything new lives under `stack/` (plus two docs).

## Global rules for every task (from the constitution and plan)

- **Do not edit `src/agentready/`**, not even `tracing.py` (FR-002, Principle I). The stack only *sets environment*
  so the existing `tracing.init()` OTLP branch exports, and *attaches context* before calling the agent. If a task
  seems to need a change there, stop and ask.
- **Stack spans never go through `agentready.tracing`.** They use `agentready_stack.telemetry`'s own
  `TracerProvider` (OTLP only), so the hash-chained audit log keeps only agent/capability/approval/rollback spans
  (research R3, data-model §3).
- Span names, attributes and statuses follow **[contracts/span-catalog.md](contracts/span-catalog.md)** exactly. An
  unknown value is **omitted, never 0** (Principle III). A barred batch, a failed verdict and an expired approval are
  `ERROR` with a pt-BR message.
- No tracing component may fail or block a run (FR-012). Every exporter or Phoenix call is wrapped so it can
  only warn.
- Every text a user sees (logs, Makefile messages, README, approval form) is **pt-BR**.
- Pins: `otel/opentelemetry-collector-contrib:0.166.0`, `arizephoenix/phoenix:version-22.0.1-nonroot` (or the
  fallback recorded in T007), `opentelemetry-exporter-otlp-proto-http` on the same release line as the locked
  `opentelemetry-sdk` in `stack/requirements/agent.txt`.
- **Never answer HITL approvals for the user.** Live runs use `autonomy_override: "shadow"`, except where a task
  explicitly needs a pending request (V-P3-7). There, stop and ask the user to approve.

---

## Phase 1: Setup and Spike Gate (Shared Infrastructure) 🚧

**Purpose**: bring up the collector and Phoenix with configuration only, and settle the three open facts
(quickstart V-P3-0).

- [X] T001 [P] Create `stack/postgres-init/02-phoenix.sql`: idempotent `CREATE ROLE phoenix LOGIN PASSWORD 'phoenix'` and `CREATE DATABASE phoenix OWNER phoenix`, guarded the same way as `stack/postgres-init/01-marquez.sql` (a DO block / `\gexec` on `pg_roles` and `pg_database`). Header comment in pt-BR: "Fase 3 — banco do Phoenix (traces); só estudo local"
- [X] T002 [P] Create `stack/config/otel-collector.yaml` per contracts/collector-pipeline.md. Receivers: `otlp` (http `0.0.0.0:4318`). Processors: `memory_limiter` (check_interval 1s, limit_mib 256), `resource` (upsert `openinference.project.name: aurora`), `transform` (trace_statements in OTTL setting `attributes["openinference.span.kind"]` per span-catalog §D: `AGENT` for `name == "agent.run"`, `TOOL` for `IsMatch(name, "^tool\\.")`, `LLM` for `name == "llm.call"`, `RETRIEVER` for `IsMatch(name, "^resource\\.")`, else `CHAIN`; set CHAIN first, then override), `batch`. Exporter: OTLP over HTTP to `http://phoenix:6006`, with `sending_queue: {enabled: true, storage: file_storage}` and `retry_on_failure: {enabled: true, max_elapsed_time: 2h}`. Extensions: `health_check` (`0.0.0.0:13133`), `file_storage` (`directory: /var/lib/otelcol/queue`). Use the exporter component name 0.166.0 documents (`otlp_http` after the 0.144 rename, or `otlphttp` if that is still the canonical one); T007 confirms it
- [X] T003 [P] In `stack/requirements/agent.in`, add `opentelemetry-exporter-otlp-proto-http` (comment: "Fase 3: o mesmo extra `otlp` do pyproject; o tracing.py exporta para o coletor"). Recompile `stack/requirements/agent.txt` with `uv pip compile --python-version 3.12 stack/requirements/agent.in -o stack/requirements/agent.txt`, and confirm the exporter matches the locked `opentelemetry-sdk` release line and that `duckdb==2.0.1` is unchanged
- [X] T004 In `stack/compose.yaml`: (a) rename service `marquez-db-init` → `db-init`, with command `sh -c 'for f in /sql/*.sql; do psql -v ON_ERROR_STOP=1 -h postgres -U airflow -d airflow -f "$f" || exit 1; done'` (`entrypoint` adjusted so `sh` runs), and point `marquez-api.depends_on` at `db-init`; (b) add service `otel-collector` (image `otel/opentelemetry-collector-contrib:0.166.0`, `user: "${AIRFLOW_UID:-50000}:0"`, `command: ["--config=/etc/otelcol/config.yaml"]`, volumes `./config/otel-collector.yaml:/etc/otelcol/config.yaml:ro` and `./data/otel-queue:/var/lib/otelcol/queue`, **no `ports:`**, a healthcheck on 13133 if the image has a probe tool, otherwise `service_started` semantics documented in a comment, `restart: unless-stopped`); (c) add service `phoenix` (image `arizephoenix/phoenix:version-22.0.1-nonroot`, env `PHOENIX_SQL_DATABASE_URL=postgresql://phoenix:phoenix@postgres:5432/phoenix`, `PHOENIX_TELEMETRY_ENABLED=false`, `PHOENIX_ALLOW_EXTERNAL_RESOURCES=false`, `PHOENIX_DISABLE_MODEL_COST_AUTO_UPDATE=true`, `PHOENIX_DISABLE_AGENT_ASSISTANT=true`, `PHOENIX_PORT=6006`; ports `"${PHOENIX_PORT:-6006}:6006"`; depends on `db-init` completed; healthcheck HTTP GET `/`; `restart: unless-stopped`); (d) in `x-airflow-common.environment` add the telemetry block from contracts/collector-pipeline.md (`AIRFLOW__TRACES__OTEL_ON: "True"`, `AIRFLOW__TRACES__TASK_RUNNER_FLUSH_TIMEOUT_MILLISECONDS: "3000"`, `OTEL_EXPORTER_OTLP_ENDPOINT: http://otel-collector:4318`, `OTEL_EXPORTER_OTLP_PROTOCOL: http/protobuf`, `OTEL_EXPORTER_OTLP_TIMEOUT: <placeholder, set by T007>`, `OTEL_SERVICE_NAME: airflow`, `PHOENIX_PORT: ${PHOENIX_PORT:-6006}`) with pt-BR comments ("Fase 3 — traces: …; se o coletor cair, nenhuma tarefa falha (FR-012)"); (e) in `airflow-init`'s command, `mkdir -p /opt/stack-data/otel-queue`
- [X] T005 In `stack/Makefile`: (a) add `PHOENIX_PORT ?= 6006` and the banner line `Traces (Phoenix) .............. http://localhost:$(PHOENIX_PORT)` in `up`; (b) `mkdir -p data/otel-queue` in `up` before compose; (c) in the `test` target, pass `OTEL_EXPORTER_OTLP_ENDPOINT=` inside both `bash -c` strings; in `parity`, prefix the command with `OTEL_EXPORTER_OTLP_ENDPOINT=` (contracts/collector-pipeline.md); (d) the `reset` help and message also name "traces (Phoenix) e a fila do coletor"; (e) add `stack-fase-3` wording to the header comment if it lists phases
- [X] T006 [P] Add `PHOENIX_PORT=6006` to `stack/.env.example` (next to the other ports, with a pt-BR comment)
- [X] T007 **Spike gate (V-P3-0):** `cd stack && make up && make run ARGS='{"reset_scenario": true, "autonomy_override": "shadow"}'`. Confirm and record in plan.md → a new "Implementation Notes" section: (1) `docker compose run --rm otel-collector validate --config=/etc/otelcol/config.yaml` passes, and which exporter component name 0.166.0 accepts (fix T002 if needed); (2) Phoenix :6006 shows project `aurora` with `worker.*` spans **during** the run and `dag_run.aurora_midia_diario` **after** it; note how Phoenix lists the trace before the root arrives (Traces tab vs Spans tab), because the runbook depends on it; (3) the unit the Python OTLP exporter reads from `OTEL_EXPORTER_OTLP_TIMEOUT` (check the installed `opentelemetry-exporter-otlp-proto-http` source), then set a value equal to **2 seconds** in `stack/compose.yaml`; (4) `/redirects/traces/<id>` opens the run's trace; (5) `docker stats --no-stream` peak. If Phoenix 22.0.1 fails any of (2)/(4), switch the image to `version-21.3.0-nonroot`, re-run, and record why. **Do not start Phase 2 until this passes**

**Checkpoint**: collector and Phoenix run; Airflow's own spans reach Phoenix; the open facts are written down.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: the stack tracer, context propagation into `agentready-stack`, and the test seams. Every story
depends on this.

- [X] T008 [P] Write `stack/tests/test_telemetry_config.py` (Airflow-env test, like `test_dag_integrity.py`, or the agent venv; reads files only): (a) `stack/compose.yaml` has services `otel-collector` (no `ports`), `phoenix` (port var `PHOENIX_PORT`, the four offline/telemetry env flags with the exact values from research R5), `db-init` (and no `marquez-db-init`); (b) `x-airflow-common` env has every variable from contracts/collector-pipeline.md; (c) `stack/config/otel-collector.yaml` parses, has the `resource` upsert `openinference.project.name=aurora`, a persistent `sending_queue` with `storage: file_storage`, and the five span-kind statements; (d) `stack/postgres-init/02-phoenix.sql` is idempotent (contains the guards). Confirm it fails before T001–T004 (or note that they already exist)
- [X] T009 [P] Write the foundational part of `stack/tests/test_telemetry.py` (agent venv). Use a fixture that gives `agentready_stack.telemetry` an **in-memory span exporter** (`telemetry.configure(exporter=...)` test hook) and points `AGENTREADY_TRACES` at a tmp dir. Tests: (a) with `TRACEPARENT=00-<32hex>-<16hex>-01` in the env, `telemetry.attach_from_env()` makes `agentready.tracing.span("x")` a child of that remote parent (same trace id, parent span id = the given one); (b) a span opened with `telemetry.span("contratos.lote", ...)` is exported by the in-memory exporter **and is not in `audit.jsonl`** (`agentready.tracing.load()` has no record with that name); (c) without `TRACEPARENT`, `attach_from_env()` is a no-op and nothing raises; (d) `telemetry.flush()` never raises when the OTLP endpoint is empty or unreachable (`OTEL_EXPORTER_OTLP_ENDPOINT=http://127.0.0.1:9`), and returns in < 5 s
- [X] T010 Create `stack/agentready_stack/src/agentready_stack/telemetry.py` (pt-BR module docstring citing research R2/R3): a **module-private `TracerProvider`** (never `trace.set_tracer_provider`) with `Resource({"service.name": "aurora-stack"})`, plus a `BatchSpanProcessor(OTLPSpanExporter())` only when `OTEL_EXPORTER_OTLP_ENDPOINT` is non-empty, with export errors swallowed and logged once in pt-BR; `configure(exporter=None)` (test hook, adds a `SimpleSpanProcessor`); `attach_from_env()` (W3C `TraceContextTextMapPropagator().extract({"traceparent": os.environ["TRACEPARENT"]})` → `opentelemetry.context.attach`, no-op when absent); `span(name, *, error: str | None = None, **attrs)` context manager (current-span parenting; values through the same convention as `agentready.tracing._attr`, implemented locally, **without** importing private names; `None` values are **omitted**; `error` sets `StatusCode.ERROR` with that pt-BR message); `common_attrs(dag_run_id, business_date, incident)` returning the span-catalog §B common attributes; `trace_url(trace_id)` / `span_url(span_id)` per contracts/trace-links.md (`None` in → `None` out; port from `PHOENIX_PORT`, default 6006); `flush()` that force-flushes **both** this provider and `agentready.tracing.flush()`, each wrapped in try/except, each bounded by a timeout (≤ 3 s)
- [X] T011 In `stack/agentready_stack/src/agentready_stack/cli.py`: call `telemetry.attach_from_env()` at the top of `main()` (before dispatch), and `telemetry.flush()` in a `finally` around the dispatch so every subcommand flushes, including failures. Update the module docstring (Phase 3: "traces: herda o contexto do Airflow via TRACEPARENT")
- [X] T012 In `stack/dags/aurora_midia_diario.py` `run_stack()`: build the subprocess env as `os.environ | (env or {})`, minus `OTEL_SERVICE_NAME`, plus `TRACEPARENT` injected from the current context (`from opentelemetry.propagate import inject`; `carrier = {}; inject(carrier)`; set `TRACEPARENT` only if `carrier.get("traceparent")`). Wrap it in try/except so a propagation problem never fails the task. Add `"stack-fase-3"` to the DAG `tags` (keep `stack-fase-2`), and mention Phase 3 traces in the module docstring
- [X] T013 [P] In `stack/tests/test_dag_integrity.py`, add `test_phase3_tags` (`"stack-fase-3"` in tags) and a test that `run_stack` puts a `TRACEPARENT` in the env passed to `subprocess.run` when a span is current, and drops `OTEL_SERVICE_NAME`. Monkeypatch `subprocess.run` and open a span with an SDK tracer
- [X] T014 Run `cd stack && make test` and `uv run pytest -q` at the repo root: T008, T009 and T013 pass, and every Phase 1/2 test still passes **unchanged**

**Checkpoint**: an `agentready-stack` subprocess started by a task joins the task's trace. Stack spans have their
own exporter and never touch the audit log.

---

## Phase 3: User Story 1 — The auditor's interrogation on a trace service (Priority: P1) 🎯 MVP

**Goal**: after a run, the agent's full span tree is in Phoenix, inside the run's trace, reachable from the
orchestrator. It is identical to the default track's tree (FR-006, FR-007, FR-009, FR-010).

**Independent Test**: quickstart V-P3-3, V-P3-4 and V-P3-11. Answer the three Block 4 auditor questions from
Phoenix alone. `make parity` shows 0 trace differences.

### Tests for User Story 1 ⚠️ write first, confirm they fail

- [X] T015 [P] [US1] Add to `stack/tests/test_telemetry.py`: with a `TRACEPARENT` set and the in-memory exporter, `tasks.run_agent("rules")` on the `built` fixture warehouse produces (a) an `agent.run` audit-log record whose `trace_id` equals the TRACEPARENT trace id; (b) an `agente.resultado` stack span with `agentready.status="done"`, `agentready.request_ids` (JSON) and `agentready.trace_url`; (c) a returned dict with `trace_url == telemetry.trace_url(trace_id)`. A second identical call → `agente.resultado` with `agentready.status="skipped_duplicate"`, an event whose message is `sem trace: já decidido para estes dados`, `trace_url is None`, and no new `agent.run` record
- [X] T016 [P] [US1] Write `stack/tests/test_trace_links.py`: `trace_url("abc")` → `http://localhost:6006/redirects/traces/abc`; `PHOENIX_PORT=7000` is honored; `trace_url(None) is None`; `span_url` likewise with `/redirects/spans/`
- [X] T017 [P] [US1] Write `stack/tests/test_trace_parity.py`: (a) **pure** tests of `parity.normalize_trace(records)` per contracts/trace-parity.md, with a hand-built record list: ids, times and hashes dropped; key `agent.run/.../<name>#<campaign_id or ordinal>`; siblings in key order; an attribute difference yields one diff with `field="attributes.<name>"`; (b) the new `parity.compare_all()` output for two equal sides validates against `specs/003-stack-traces-dashboards/contracts/parity-report.schema.json` (2.1.0) and has `compared.traces.diffs == []`; (c) `compare()` still returns 1.0.0 and **`compare_full()` still returns 2.0.0** (no `traces` key), so `test_parity.py` and `test_parity_phase2.py` pass unchanged; (d) `parity.run("manha")` returns 2.1.0 with `compared.traces.diffs == []`

### Implementation for User Story 1

- [X] T018 [US1] In `stack/agentready_stack/src/agentready_stack/tasks.py` `run_agent()`: keep the agent call exactly as is (it already inherits the attached context). Around the result, open `telemetry.span("agente.resultado", **telemetry.common_attrs(...), **{"agentready.status": ..., "agentready.request_ids": [...], "agentready.trace_url": ...})`. On a skip, add the event `sem trace: já decidido para estes dados`. Add `"trace_url": telemetry.trace_url(rep.trace_id)` (or `None`) to **both** return dicts. Log `Trace desta execução no Phoenix: <url>` or `Sem trace: já decidido para estes dados (execução pulada).` (contracts/trace-links.md). Derive `business_date` from `reference_ts`/today in America/Sao_Paulo, and `incident` from the run's `ops.stack_run_settings` row or the last `incidents` record for this run (never reveal the type for `aleatorio`)
- [X] T019 [US1] In `stack/agentready_stack/src/agentready_stack/parity.py`: in `_side()`, after `ReadyAgent("rules").run(con)`, call `agentready.tracing.flush()` and include `"trace": normalize_trace(tracing.load(rep.trace_id))` in the returned dict. Add pure `normalize_trace(records)` per contracts/trace-parity.md (subtree from `agent.run`; kept and dropped fields exactly as listed). Leave `compare_full()` unchanged (2.0.0). Add `compare_all(default, stack, scenario, ref)`, which calls `compare_full()`, then diffs `traces` keyed by path with fields `status`, `status_message`, `attributes.<k>` (one per attribute) and `events`. It sets `report["compared"]["traces"] = {"items": n, "diffs": diffs}` and ANDs the result into `report["ok"]`, producing 2.1.0. `run()` and the CLI `--json` path call `compare_all()` and validate against the 2.1.0 schema (copy `contracts/parity-report.schema.json` to wherever the 2.0.0 schema is loaded today and bump the reference). Docstring: "compare() = 1.0.0 (Fase 1), compare_full() = 2.0.0 (Fase 2), compare_all() = 2.1.0 (Fase 3)."
- [X] T020 [US1] Add `agentready-stack traces [--limit N]` (default 10) in `stack/agentready_stack/src/agentready_stack/cli.py`, implemented in a new function `traces(limit)` in `stack/agentready_stack/src/agentready_stack/incidents_cli.py`: read `ops.agent_runs` (newest first: `dag_run_id`, `business_date`, `status`, `trace_id`) joined with `ops.stack_run_settings` for the incident where available, and print the pt-BR table `execução · data de negócio · incidente · agente · link` (`link` = `trace_url` or `—` with "sem trace (pulado)"), then the JSON last line `{"runs": [...]}`. Add `make traces` (help: "Fase 3: últimas execuções com o link do trace no Phoenix") to `stack/Makefile`, following the `decisoes` pattern (strip the JSON line)
- [X] T021 [US1] Run T015–T017 (`make test`), then **V-P3-3** live: `make run ARGS='{"autonomy_override": "shadow"}'`, open the link from the `agente.executar` log. Confirm the tree `dag_run → worker.agente.executar → agent.run` and that the three auditor answers are on spans (C01 budget span attributes; versions; C03/Meta refusal as ERROR with the feed and rule). Then **V-P3-4** (same run again → skip). Then `make parity SCENARIO=todos` → `compared.traces.diffs` empty in all 7 scenarios. If a real difference appears, **stop and report it** (Principle I). Do not add a normalization rule without the user's agreement. Record the results in plan.md → Implementation Notes

**Checkpoint**: Block 4's auditor exercise works in Phoenix. Agent traces are proven identical across tracks.

---

## Phase 4: User Story 2 — One run, from ingestion to decision, in one place (Priority: P2)

**Goal**: domain spans for ingestion, contract batches, observability verdicts and the run summary; approval
spans in the same trace; a link from the approval form; rollback linked to the original decision (FR-004,
FR-005, FR-007, FR-008).

**Independent Test**: quickstart V-P3-5 to V-P3-8.

### Tests for User Story 2 ⚠️ write first, confirm they fail

- [X] T022 [P] [US2] Add to `stack/tests/test_telemetry.py` (in-memory exporter): (a) `run_incident("lote_duplicado")`, then `tasks.quality_alert()` (expect `QualityAlert`): a `contratos.lote` span for the barred ga4 batch has `ERROR` status, a message starting `lote <batch_id> barrado: quarentena`, and the attributes `contract`, `batch_id`, `rows`, `quarantined_rows`, `quarantine_rate`, `max_quarantine_rate`, `batch.status="barred"`, `barred_by`; passed batches in the same run are `OK` with `batch.status="passed"` and **no** `barred_by`; the spans are exported **before** the exception propagates; (b) `run_incident("centavos")`, then `tasks.observe()` (expect `ObservabilityAlert`): `observabilidade.veredito` for distribution/ga4 is `ERROR` with `ratio`, `observed` and `baseline`; with the `short_history` fixture, the verdict span is `OK` with `agentready.status="histórico insuficiente"` and **no** `ratio` attribute (unknown ≠ 0); (c) `tasks.ingest({...})` emits `ingestao.parametros` with `agentready.breaker.value`/`source` and `agentready.incident`; with `incident="aleatorio"` the attribute is `aleatorio`; (d) under a TRACEPARENT, `tasks.apply_decision(req, payload)` for an approve and for an expiry (`payload=None`) writes `human.approval` / `human.approval_expired` audit records **with the TRACEPARENT's trace id**; (e) `tasks.close_run()` emits `fechamento.resumo` with `stale_sources` (JSON) and `pending_requests`
- [X] T023 [P] [US2] Add to `stack/tests/test_trace_links.py`: `approvals.to_hitl_kwargs(details)["body"]` contains `[Abrir o raciocínio do agente no Phoenix](http://localhost:6006/redirects/traces/<trace_id>)` on the line after `Trace:`, and the subject, options and the rest of the body are unchanged from Phase 1 (`contracts/approval-request.md` of spec 001); `incidents_cli.decisions_since("")` rows include a `trace_url` key
- [X] T024 [P] [US2] Write `stack/tests/test_rollback_link.py`: run the agent so a change executes (fixture as in `test_agent_stage.py`), then `rollback.run(change_id, actor="instrutor")`: (a) an in-memory `humano.rollback` span with `change_id`, `actor`, `agentready.original_trace_id`, `agentready.original_trace_url`, and **one link** whose context is the original `agent.run` span (trace id and span id read from the audit log); (b) the audit log gains a `human.rollback` record whose parent is the `humano.rollback` span (same trace); (c) an unknown change id gives a pt-BR error and exit code 1, with no span link; (d) the returned JSON has `original_trace_url`

### Implementation for User Story 2

- [X] T025 [US2] In `stack/agentready_stack/src/agentready_stack/tasks.py` `ingest()`: wrap the body's result in `telemetry.span("ingestao.parametros", **common_attrs, **{"agentready.applied": applied, "agentready.reference_ts": ..., "agentready.breaker.value": ..., "agentready.breaker.source": ..., "agentready.autonomy_override": p["autonomy_override"]})` (span-catalog §B)
- [X] T026 [US2] In `tasks.py` `quality_alert()`: after the watermark query, **also** select every batch in `meta.batch_status` with `ingested_at > watermark` (all statuses, joined to `meta.contract_registry`). For each, open a `contratos.lote` span with the span-catalog attributes (`quarantined_rows` and `rows` from `meta.batch_status`; omit any that are NULL). Barred → `error=f"lote {batch_id} barrado: {motivo}"`, with `motivo` reusing the existing pt-BR reason strings (`quarentena X% > limite Y%`, or `anomalia de distribuição (ticket médio fora da faixa)`). Make sure the spans end **before** `QualityAlert` is raised. Behavior and messages are otherwise unchanged
- [X] T027 [US2] In `tasks.py` `observe()`: for each verdict, a `observabilidade.veredito` span with `pillar`, `target`, `agentready.status` (`pass`, `fail`, or `histórico insuficiente` for `warn`), and `observed`/`baseline`/`ratio` only when present in the verdict row. `fail` → `error=` the verdict's existing pt-BR detail. Spans end before `ObservabilityAlert` is raised. Check which columns `meta.observability_checks` exposes (`agentready_stack/observe.py` `verdicts()`), and add the numeric fields to `verdicts()` only if missing, keeping its existing keys
- [X] T028 [US2] In `tasks.py` `close_run()`: emit `fechamento.resumo` with `stale_sources`, `pending_requests` and `lineage.ok`; warnings go in as span **events**, never ERROR. (`traces.ok`/`traces.reason` come in US3, T036)
- [X] T029 [US2] In `stack/agentready_stack/src/agentready_stack/approvals.py` `to_hitl_kwargs()`: insert `f"[Abrir o raciocínio do agente no Phoenix]({telemetry.trace_url(d['trace_id'])})"` right after the existing `Trace: …` line, only when `trace_url` is not None. Nothing else in the form changes
- [X] T030 [US2] Create `stack/agentready_stack/src/agentready_stack/rollback.py` with `run(change_id, actor) -> dict`. Look up `trace_id` in `ops.change_log` (unknown → `ValueError("alteração <id> não encontrada")`). Find that trace's `agent.run` span id in `agentready.tracing.load(trace_id)`. Open `telemetry.span("humano.rollback", links=[Link(SpanContext(trace_id, span_id, is_remote=True, trace_flags=SAMPLED))], ...)` (extend `telemetry.span` with an optional `links` param), and **inside** it call the same shared function `agentready rollback` uses (find it in `src/agentready/cli.py` `cmd_rollback` and call it, do not copy it). Print `Decisão original: <trace_url>` and return `{"change_id", "status", "original_trace_url"}`. Add `agentready-stack rollback <CHG> [--by ACTOR]` to `cli.py` (exit 1 with `FALHA: …` on ValueError). Change `make rollback` in `stack/Makefile` to `$(RUN) '$(AGENT)/agentready-stack rollback $(CHG) --by instrutor | sed "\$${/^[{]/d}"'`
- [X] T031 [US2] In `stack/agentready_stack/src/agentready_stack/incidents_cli.py` `decisions_since()`: add `trace_url` to each row and replace `· trace {id}` in the printed line with `· trace {trace_url or id}` (contracts/trace-links.md). Keep the JSON keys of Phase 2 (additive only)
- [X] T032 [US2] Run T022–T024 (`make test`), then live: **V-P3-5** (`lote_duplicado`), **V-P3-6** (`centavos`), **V-P3-8** (rollback of a change from a non-shadow run: use `make run ARGS='{"reset_scenario": true}'` only after asking the user, since it may queue approvals). For **V-P3-7** (approval link), trigger `make run ARGS='{"autonomy_override": "supervised"}'`, then **ask the user to open the request as `aprovadora` and approve one / let one expire**. Never answer it yourself. Record the results in plan.md → Implementation Notes

**Checkpoint**: one trace shows the whole run. Approvals and rollbacks lead back to the decision.

---

## Phase 5: User Story 3 — The audit record stays tamper-evident (Priority: P2)

**Goal**: verify the stack's hash-chained log; no decision is lost when the collector or Phoenix is down (FR-011,
FR-012, SC-005, SC-006).

**Independent Test**: quickstart V-P3-9 and V-P3-10.

### Tests for User Story 3 ⚠️ write first, confirm they fail

- [X] T033 [P] [US3] Write `stack/tests/test_audit_stack.py` (agent venv, tmp `AGENTREADY_TRACES`): (a) run the agent under a TRACEPARENT, then `agentready.tracing.verify_chain()` → `(True, n, "cadeia íntegra")`, and `tracing.tree(tracing.load(tid))` has `agent.run` as a root even though its `parent_span_id` isn't in the file; (b) edit one attribute value in the file, then `verify_chain()` → `False` with a message naming the record (`conteúdo alterado (<name>)`); (c) the audit log contains **no** record whose name is in span-catalog §B (stack spans stay out)
- [X] T034 [P] [US3] Add to `stack/tests/test_telemetry.py`: `telemetry.phoenix_has_trace(trace_id, timeout=…)` returns `{"ok": False, "reason": <pt-BR>}` against an unreachable URL in < 5 s and never raises; `close_run()` with Phoenix unreachable returns normally with `traces.ok == False` and prints the R6 warning containing `make auditoria`

### Implementation for User Story 3

- [X] T035 [US3] In `telemetry.py`, add `phoenix_has_trace(trace_id, attempts=6, wait_s=5)`: POST `http://phoenix:6006/graphql` (base from env `PHOENIX_INTERNAL_URL`, default `http://phoenix:6006`) with `query { getTraceByOtelId(traceId: "<id>") { id } }`, retrying up to ~30 s (SC-004). Return `{"ok": True}`, or `{"ok": False, "reason": …}` with pt-BR reasons: Phoenix unreachable, or reachable but trace not yet present. Separately check the collector's health endpoint (`http://otel-collector:13133/`) to tell "coletor fora do ar" from "Phoenix fora do ar (spans na fila do coletor, serão entregues quando ele voltar)". Never raise. Add `PHOENIX_INTERNAL_URL: http://phoenix:6006` to the airflow-common env in `stack/compose.yaml`
- [X] T036 [US3] In `tasks.py` `close_run()`: read the run's agent `trace_id` from `ops.agent_runs` for `dag_run_id`. Skip the check when the agent was skipped or didn't run (say so). Otherwise call `phoenix_has_trace`, and add `traces: {ok, reason, url}` to the return dict and `traces.ok`/`traces.reason` to `fechamento.resumo`. Append to the summary `Traces: no Phoenix (<url>).`, or log `AVISO — o trace <id> ainda não está no Phoenix (<motivo>); as decisões estão no log de auditoria — make auditoria.` The task **never fails** because of this
- [X] T037 [US3] Add `make auditoria` to `stack/Makefile` (help: "Fase 3: verifica a cadeia de hash do log de auditoria da trilha stack"): `$(RUN) '$(AGENT)/agentready verify'`. The env already points `AGENTREADY_TRACES` at `/opt/stack-data/traces`. Its exit code is the command's
- [X] T038 [US3] Extend `stack/scripts/lineage_live_check.py` (keep its Phase 2 checks; update the docstring to "Fase 2 e 3"): (a) after run A, fetch the agent subtree from Phoenix via GraphQL by trace id and compare it with the audit log copy using `parity.normalize_trace`, with `openinference.*` and resource attributes dropped (contracts/trace-parity.md): 0 diffs; (b) run D: start a run, `docker compose stop phoenix` after `agente.executar` starts, wait for the run to end, then check the run state equals run A's, `make auditoria` exits 0, and `fechamento` logged the "fila do coletor" warning; `docker compose start phoenix`, wait ≤ 2 min, and the run's trace appears in Phoenix (queue drained); (c) run E: `docker compose stop otel-collector` for the whole run, then check the run state equals A's, its duration is at most A's + 60 s, the "coletor fora do ar" warning is logged, and every executed decision of E is in the audit log; restart the collector; (d) **SC-004**: for run A, read `end_date` of the `agente.executar` task instance from the Airflow API, then poll Phoenix GraphQL `getTraceByOtelId` for an `agent.run` span every 2 s. Assert the gap is ≤ 30 s and print it; (e) **FR-003**: after run A, `docker compose down && make up` (without `reset`). Run A's trace still resolves at `/redirects/traces/<id>`, and a Phoenix span query filtered on `attributes["agentready.business_date"]` and on `attributes["airflow.dag_run.run_id"]` returns run A's spans; (f) **Agent not reached** (spec edge case): trigger a run that makes an `observabilidade.verificar` model fail, using the same failure trick the Phase 2 tests use for FR-008b. Assert that the `dag_run.aurora_midia_diario` span ends in the failed state, that the trace has no `agent.run` span, and that the orchestrator marks `agente.executar` as `upstream_failed`. All runs use `autonomy_override: "shadow"`
- [X] T039 [US3] Run T033–T034 (`make test`), then **V-P3-9** (`make auditoria` → edit `stack/data/traces/audit.jsonl` on a **copy-backed** test: back up the file first, restore it after) and **V-P3-10** (`make test-live`). Record the results, the run-time deltas and the measured SC-004 gap in plan.md → Implementation Notes

**Checkpoint**: the hash chain is still the proof on the stack, and outages cost a warning, not decisions.

---

## Phase 6: User Story 4 — The guide and instructor script cover Phase 3 (Priority: P3)

**Goal**: the reader and the instructor can present Phase 3 truthfully (FR-014, FR-019, FR-020).

**Independent Test**: quickstart V-P3-14. A newcomer follows the guide from a clean checkout to the three auditor
answers in Phoenix.

- [X] T040 [US4] Update `stack/README.md` (pt-BR): (a) line 3 intro + prerequisites: Phase 3 (traces no Phoenix), **4 URLs** (Airflow, Marquez, relatório, Phoenix :6006), RAM minimum still 8 GB with the peak measured in T007/T045; (b) "Mapa de substituição": add a "Ferramenta (Fase 3)" table with the plan.md "Replacement map additions" rows (Airflow traces nativos, OpenTelemetry Collector 0.166.0, Arize Phoenix <pinned version>), and a **"Substituição parcial, com honestidade"** bullet: "a cadeia de hash continua sendo o registro de auditoria: o Phoenix é para explorar, não é à prova de adulteração — `make auditoria` é a prova"; (c) "Lacunas conhecidas": remove "Traces e painéis continuam como na trilha padrão… até a Fase 3" and add the research R11 gaps, worded for the audience; (d) "Roteiro das próximas fases": Phase 3 row ✅ with "OpenTelemetry Collector + Arize Phoenix" and "**feito:** …", plus a sentence: "**Grafana saiu do roteiro:** nenhum módulo da trilha padrão para ele substituir (Princípio VI); os painéis do próprio Phoenix bastam para o Bloco 4"; Langfuse is mentioned as the alternative rejected for RAM; (e) a new section "**Bloco 4 na trilha stack (Fase 3)**" with the runbook: `make run`, open the link in the `agente.executar` log (or `make traces`), the three auditor questions and **which span/attribute answers each**, the approval link, `make auditoria` and the tampering exercise on `data/traces/audit.jsonl`, and what to do when the root span hasn't arrived yet (from T007's finding); (f) the commands `auditoria`, `traces`, the changed `rollback`; (g) "Estrutura": `config/otel-collector.yaml`, `postgres-init/02-phoenix.sql`, `agentready_stack/telemetry.py`, `rollback.py`; (h) "Problemas comuns": Phoenix shows no trace yet (root at run end, or collector down → `make logs SVC=otel-collector`), port 6006 busy (`PHOENIX_PORT`), the stack `trace_id` is now the run's trace, and the trace has no `agent.run`: an earlier step failed, so the agent didn't run (fail-safe). The `dag_run` span is red, and the Airflow graph shows the step that failed
- [X] T041 [P] [US4] Update `docs/01-roteiro-do-instrutor.md`: in Bloco 4, add "**Na trilha stack (Fase 3)**" with the stack runbook (matching the default-track teaching points: one trace per decision, the attributes, the hash chain intact and then tampering detected, the approval re-checking live state, shadow mode) and the honest line "explore no Phoenix, prove com a cadeia de hash". In Bloco 5, add the stack triage tools `make traces` and the Phoenix link next to `make decisoes`. Update line 19 (the optional Phoenix mention) to say the stack track brings Phoenix running already
- [X] T042 [P] [US4] Update `docs/02-exercicios.md` Bloco 4: a "**Trilha stack**" variant of exercise 1 (answer from Phoenix via `make traces`) and exercise 4 (edit `stack/data/traces/audit.jsonl`, then `make auditoria`). Keep exercise 5 (default-track Phoenix with `docker run`) unchanged (FR-016)
- [X] T043 [P] [US4] In the root `README.md`, where the stack track or its phases are summarized (and the "Traces no Arize Phoenix / Langfuse (opcional)" section), add one pt-BR line: the stack track already runs Phoenix with pipeline and agent traces (Phase 3). The default-track instructions stay unchanged

**Checkpoint**: the guide, script and exercises match what runs.

---

## Phase 7: Polish & Cross-Cutting Concerns

- [X] T044 [P] Review every new or changed pt-BR string (logs, Makefile, README, approval form) for consistency with Phase 1–2 wording ("execução", "lote", "barrado", "trace", "log de auditoria"), and make sure no English user-facing text slipped in
- [X] T045 **SC-007**: during a full run (`make run ARGS='{"reset_scenario": true, "autonomy_override": "shadow"}'`), sample `docker stats --no-stream` every 5 s, and record the peak total and per service (Phoenix, collector) in `stack/README.md` (prerequisites) and plan.md → Implementation Notes. If the peak puts the 8 GB minimum at risk (> 6 GB), stop and report
- [X] T046 **V-P3-13 offline**: with the images already pulled, disconnect the network (or `docker network disconnect` for the host's external route; ask the user if this needs privileges), `make down && make up`, run once, and confirm the Phoenix UI loads fully (no external fonts) and the trace arrives. Record the result — **done 2026-11-27 together with 004 T074; see 004 plan.md → "Offline run (T074 + 003 T046)"**
- [X] T047 **Full gate**: `uv run pytest -q` (repo root, unchanged suite), `cd stack && make test`, `make parity SCENARIO=todos` (0 diffs in all sections, report 2.1.0), `make test-live`, then a **clean-checkout** run (`git clone` into a temp dir, `make up`, `make run`, Phoenix link works). Record the timings and results in plan.md → Implementation Notes and in the README's "Tempos medidos" (a "Fase 3" subsection)
- [X] T048 Leave for the user (do not simulate): **SC-001** (a newcomer answers the 3 auditor questions in Phoenix in ≤ 5 min) and **SC-009** (Block 5 triage via Phoenix is no slower than `trace last`/`lineage --since`) need a person with a stopwatch. Add both as "a medir" rows in the README's timing table, and tell the user in the final report
- [X] T049 Update `specs/003-stack-traces-dashboards/spec.md` **Status** to "Implemented" and close out every Implementation Notes item in plan.md (versions pinned, spike facts, measured numbers)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Setup + spike gate)**: no dependencies. **T007 gates everything after it.**
- **Phase 2 (Foundational)**: after T007. Blocks every story.
- **US1 (Phase 3)**: after Phase 2. This is the MVP.
- **US2 (Phase 4)**: after Phase 2. Independent of US1 except T029, which uses `telemetry.trace_url` (T010), and
  T031, which shares `incidents_cli.py` with T020, so do them in sequence.
- **US3 (Phase 5)**: after Phase 2. T036 edits `close_run()` after T028 (US2) if both are done, so do them in sequence.
  T038 uses `parity.normalize_trace` (T019, US1).
- **US4 (Phase 6)**: after the stories it documents (US1–US3) and T007/T045 for the numbers.
- **Polish (Phase 7)**: last.

### Within Each User Story

- Tests first (they must fail), then implementation, then the live validation task at the end of the phase.
- `tasks.py` is touched by T018, T025–T028 and T036: do those **in sequence** (same file).

### Parallel Opportunities

- Phase 1: T001, T002, T003 and T006 together, then T004 → T005 → T007.
- Phase 2: T008, T009 and T013 (tests) together; then T010 → T011; T012 independent of T011.
- US1 tests T015, T016 and T017 together. US2 tests T022, T023 and T024 together. US3 tests T033 and T034 together.
- US4: T041, T042 and T043 together (different files), after T040's runbook content is settled.

---

## Parallel Example: User Story 2

```bash
# Tests first, in parallel (different files):
Task: "T022 [US2] domain-span tests in stack/tests/test_telemetry.py"
Task: "T023 [US2] approval-link test in stack/tests/test_trace_links.py"
Task: "T024 [US2] rollback-link tests in stack/tests/test_rollback_link.py"

# Then, in parallel (different files):
Task: "T029 [US2] approval link in approvals.py"
Task: "T030 [US2] rollback.py + CLI + make rollback"
# and in sequence (same file tasks.py): T025 → T026 → T027 → T028
```

---

## Implementation Strategy

### MVP First (User Story 1 only)

1. Phase 1, including the spike gate T007.
2. Phase 2 (foundational).
3. Phase 3 (US1): the agent's trace is in Phoenix, inside the run's trace, linked from the task log; trace
   parity is 0.
4. **Stop and validate**: the Block 4 auditor exercise runs on the stack track.

### Incremental Delivery

1. + US2: the whole run in one trace; approval and rollback links.
2. + US3: `make auditoria`; outage behavior proven live.
3. + US4: guide, script, exercises.
4. Polish: RAM, offline, clean checkout. SC-001 and SC-009 are timed by the user.

---

## Notes

- [P] tasks = different files, no dependency on an unfinished task.
- Commit after each task or logical group. Never commit `stack/.env`, `stack/config/passwords.json` or anything
  under `stack/data/`.
- If a live check fails because of the environment (ports, RAM, network), report it with the output. Don't
  weaken a test to pass.
