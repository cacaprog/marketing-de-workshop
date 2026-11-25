# Feature Specification: Stack Track Phase 3 — Traces and Audit Record

**Feature Branch**: `003-stack-traces-dashboards`

**Created**: 2026-11-25

**Status**: Implemented — pending manual validations: V-P3-13 (offline), clean checkout, SC-001/SC-009 (stopwatch)

**Input**: User description: "phase 3". This is the next phase of the stack-track roadmap defined in `specs/001-stack-production-track/spec.md` (FR-025) and `stack/README.md` ("Roteiro das próximas fases"): an **OpenTelemetry Collector + Phoenix or Langfuse + Grafana** replace `tracing.py` and the hash-chained JSONL log (Block 4), so that pipeline traces and agent traces sit in one place, with dashboards.

## Context

Phases 1 and 2 (`specs/001-stack-production-track`, `specs/002-stack-lineage-observability`) put the daily Aurora media run on production tools: orchestrator, transformation framework, contract validation, human approvals, data observability and lineage. One gap from the roadmap is still open and documented in `stack/README.md` → "Lacunas conhecidas": **"Traces e painéis continuam como na trilha padrão (`agentready trace`) até a Fase 3."**

Today, on the stack track:

1. **Agent traces are written the same way as on the default track.** The shared tracing code exports every span to a hash-chained JSONL file (`stack/data/traces/audit.jsonl`). The only way to read a trace is the terminal tree and the generated HTML page (`agentready trace`, `tracing.render_html`). There is no trace service.
2. **The pipeline produces no traces.** Orchestrator tasks, contract checks, quarantine, the circuit breakers and the observability step appear in the orchestrator's UI and in lineage, but not as spans. A Block 4 auditor can't follow one run from ingestion to the agent's decision in a single view. Lineage (Phase 2) shows *which datasets* fed the agent. It doesn't show *what happened, when and why* inside the run.
3. **Approvals are disconnected from their reasoning.** An approval request in the orchestrator shows the `trace_id` as text. The approver can't open the trace that explains why the agent asked.

Phase 3 closes the gap. It applies the same rule as Phases 1 and 2: **a tool joins the stack only if it replaces an existing module.**

| Capability | Replaces (default track) | Block |
|---|---|---|
| Collecting spans from the agent and the pipeline and routing them to storage | the export half of `tracing.py` (`HashChainJsonlExporter`, the optional OTLP branch in `init()`) | 4 |
| Storing traces and exploring them (search, span tree, attributes, errors) | `agentready trace` (list, terminal tree) and `tracing.render_html()` | 4, 5 |
| Tamper evidence for the audit record | **not replaced** (partial replacement, documented): the hash-chained log and `verify_chain()` stay the record of truth (FR-011) | 4 |

The span-producing calls inside the shared agent and capabilities (`tracing.span(...)`, `set_attrs`, `fail`) **don't change** (Principle I: one agent source for every track). Phase 3 changes where spans go, what else produces spans, and how people read them.

**Dashboards are out of Phase 3.** The roadmap listed Grafana, but it can't name a module it would replace (Principle VI). The trace service's own views (search, span tree, errors) cover Block 4. Grafana comes off the roadmap until a proposal names the module it replaces (FR-013, FR-014).

The Block 4 lesson stays the same, and the stack track can now teach it with production tools: **logs say *what* was accessed; an audit asks *why*. One trace per decision answers it.**

## Clarifications

### Session 2026-11-25

- Q: Which component holds the tamper-evident audit record once a trace service stores the spans? → A: The existing hash-chained log stays the record of truth, written by the shared tracing code alongside the export to the trace service. The trace service is the exploration view. This is a partial replacement, documented in the guide (Option A).
- Q: What do the dashboards show, and which module do they replace? → A: No separate dashboard tool in Phase 3. The trace service's own views are enough, and the dashboard tool comes off the roadmap until it can name a module it replaces (Option B).
- Live validation 2026-11-25 (V-P3-7): the shared code records no span for a REJECTED request, only for approval and expiry. FR-008 is met by the stack span `humano.decisao`, which records every outcome in the run's trace. Agent code is unchanged.
- Implementation 2026-11-25: US1 AS3 was corrected. The shared agent records a stale-data refusal as `sem_dados` in `agent.reasoning` (plus `result.stale_campaigns` / `data.stale_sources`), not as an error span, on both tracks. FR-015's error rule applies to the spans the stack produces.
- Analysis 2026-11-25: FR-004 was narrowed to steps that ran. Tasks that never start have no span in the orchestrator's tracing (research R11 #3).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - The auditor's interrogation on a trace service (Priority: P1)

After a daily run on the stack, the instructor (or a squad) opens the trace service in the browser, finds the agent's run for that business date, and answers the Block 4 "interrogatório do auditor" without the terminal: why did C01's budget go up, and based on which number; which semantic-model and guardrail versions were in force; why nothing was done with C03. Each answer is a span attribute or a span error in the agent's trace: the sources read, the query, the contract and semantic versions, the preconditions that passed or failed, and the autonomy level.

**Why this priority**: This is the Block 4 exercise and the reason the trace service exists. Without it, the stack track still depends on the default track's terminal tooling to teach traceability.

**Independent Test**: Trigger one daily run with no incident. In the trace service, open the agent's trace for that run and answer the three auditor questions from its spans alone. Compare its span names and decision attributes with the default track's trace for the same scenario.

**Acceptance Scenarios**:

1. **Given** a finished daily run in which the agent ran, **When** the user searches the trace service for that run (by business date or by the run's `trace_id` shown in the orchestrator), **Then** the agent's trace opens with the same span tree the default track produces (`agent.run` → reasoning, tool and resource spans), and every span carries its attributes and status.
2. **Given** the agent's trace from scenario 1, **When** the user expands the budget-change span for C01, **Then** the span shows the metric value it used, the semantic-model and guardrail versions, the precondition results and the autonomy level that applied.
3. **Given** a run in which a campaign's source feed is stale (the default scenario's Meta feed), **When** the user opens the agent's trace, **Then** the refusal is visible on the agent's spans: `agent.reasoning` marks the campaign `sem_dados`, `tool.get_campaign_performance` lists it in `result.stale_campaigns`, and `tool.get_data_health` names the stale feed in `data.stale_sources`. These are the same spans and attributes the default track records. The shared agent code doesn't mark a refusal as an error span, and Phase 3 doesn't change it (Principle I).
4. **Given** a run the agent skipped as a duplicate ("já decidido para estes dados"), **When** the user looks for its trace, **Then** the orchestrator says no trace exists for that run and why, and the trace service has no new agent trace for it.
5. **Given** the optional Claude brain is used for a run, **When** the user opens that trace, **Then** the model-call spans the shared agent emits are shown too. The default (rules brain) run has none.

---

### User Story 2 - One run, from ingestion to decision, in one place (Priority: P2)

The instructor opens the trace for one daily run and sees the pipeline and the agent together: ingestion, contract checks (with the quarantine count and the circuit-breaker verdict per batch), cleaned and business layers, the observability verdicts, the agent's decision spans and any approval request. A blocked batch, a failed check or an expired approval is a span with error status that says what happened. From an approval request in the orchestrator, the approver opens the trace that explains why the agent asked.

**Why this priority**: This makes the scenario realistic: "traces de pipeline e de agente num só lugar". It turns Block 5 triage into one timeline. It comes after P1 because the agent's trace must be browsable before the pipeline is attached to it.

**Independent Test**: Trigger a run with the `lote_duplicado` incident. In the trace service, confirm that the run's pipeline spans and the agent's spans are reachable from each other, and that the blocked batch appears as an error span naming the batch and the breaker. Open an approval request in the orchestrator and follow it to its trace.

**Acceptance Scenarios**:

1. **Given** a finished daily run, **When** the user opens the run in the trace service, **Then** every pipeline step that ran (ingestion, contract stage, cleaned layer, business layer, observability, agent, approval wait) is a span with its duration and status, and the agent's decision trace is reachable from it in at most two navigation steps. The reverse also holds.
2. **Given** a run with the `lote_duplicado` incident, **When** the contract stage blocks the batch, **Then** the contract-stage span names the feed, the batch, the quarantined row count and the breaker reason, and has error status.
3. **Given** a run with the `centavos` incident and the distribution breaker off, **When** the run finishes, **Then** the observability span records the failed distribution verdict (feed, batch, ratio), and the agent's spans in the same run show that the agent still decided on that data. That is the incident.
4. **Given** a pending approval request, **When** the approver opens it in the orchestrator, **Then** a link opens the agent trace that produced the request. When the approver decides, the decision (approve, reject or expiry) appears as a span tied to that request and its original trace.

---

### User Story 3 - The audit record stays tamper-evident (Priority: P2)

The instructor shows that the stack's audit record of agent decisions can't be edited silently: the stack's verify command reports the record intact after a run, and reports the exact broken record after someone edits a stored decision. The hash-chained log stays the record of truth. The trace service is where people explore, not what the auditor verifies (FR-011).

**Why this priority**: Tamper evidence is a promise Block 4 makes on stage ("log à prova de adulteração"). Phase 3 must not quietly drop it while replacing the module that delivered it. It is P2 because the trace service (P1) can be demonstrated first.

**Independent Test**: Run the daily pipeline, then run the stack's verify command: it reports the record intact. Edit one stored decision value, verify again: it names the altered record.

**Acceptance Scenarios**:

1. **Given** one or more finished runs, **When** the user runs the stack's verify command, **Then** it reports the audit record intact and how many records it checked.
2. **Given** an edited value in one stored decision record, **When** the user runs the verify command, **Then** it reports a broken record and identifies which one.
3. **Given** the trace service is down during a run, **When** the run finishes, **Then** no decision the agent executed is missing from the audit record. See FR-012.

---

### User Story 4 - The guide and instructor script cover Phase 3 (Priority: P3)

A reader of the stack guide sees the new tools in the replacement map, each with the module it replaces and the block it supports. "Lacunas conhecidas" no longer says traces stay on the default track. It lists any honest partial replacement, including that the hash-chained log stays the audit record. The roadmap shows Phase 3 as done, and the dashboard tool is removed from it, with the reason. The instructor script explains how to run Block 4 (and the trace part of Block 5 triage) on the stack track.

**Why this priority**: Phase 1 and 2 set this documentation pattern. Without it, the instructor can't present Phase 3 truthfully. It ships last because it describes the finished behavior.

**Independent Test**: A person who hasn't seen Phase 3 follows the guide from a clean checkout to the auditor's three answers in the trace service.

**Acceptance Scenarios**:

1. **Given** the stack guide, **When** a reader looks up any Phase 3 tool, **Then** the replacement map names the module it replaces and the block it supports, and notes any partial replacement.
2. **Given** the instructor script, **When** the instructor prepares Block 4, **Then** it has a stack-track runbook: which URL to open, which run to pick, and where each auditor answer is.

---

### Edge Cases

- **Trace service down or slow**: the daily run never waits on or fails because of the trace service. Spans produced while it is down are not lost: they are buffered and delivered when it returns, or the audit record keeps them (FR-012). The guide says what the user sees meanwhile.
- **Duplicate run skipped**: no agent trace is created. The orchestrator and the trace service say so explicitly instead of showing an empty trace.
- **Run with the agent not reached** (e.g., an observability model fails and the agent stays off — fail safe): the run's trace shows the pipeline spans up to the failure and states that the agent did not run.
- **Delayed approval**: an approval decided hours after the run (or expiring) still appears linked to the original request and its trace. It is not an orphan trace.
- **Rollback during triage**: a rollback is a span linked to the change it reverses and to that change's original decision trace.
- **Stack reset**: `make reset` clears the stored traces and the audit record along with the rest of the stack's data, and never touches the default track's `traces/`.
- **Clock and time zone**: span times show in the instructor's local time (the scenario's business dates are in America/Sao_Paulo). Business date and wall-clock time are never mixed up in search.
- **Many runs in one day** (Block 5 has squads re-running): the user can tell runs apart by business date, run id and incident, not only by timestamp.
- **Sensitive content in spans**: spans may carry briefing text marked untrusted. The trace service shows it as data and never as instructions. Spans never carry credentials or the API key.

## Requirements *(mandatory)*

### Functional Requirements

**Collection and storage**

- **FR-001**: The stack track MUST run a trace collector that receives spans from the shared agent code and from the pipeline and routes them to the trace store. No span is sent to any service outside the host.
- **FR-002**: The shared agent and capability code MUST stay unchanged in what spans they create and what attributes they set (Principle I). Phase 3 MAY change only where spans are exported to, through configuration that the default track doesn't set.
- **FR-003**: The trace store MUST keep traces across stack stop/start and lose them only on `make reset`. Stored traces MUST be searchable by business date, run id, `trace_id`, campaign and incident.
- **FR-004**: The pipeline MUST emit spans for every step of the daily run: ingestion, contract stage (per feed and batch, with quarantined row count and breaker verdict), cleaned layer, business layer, observability verdicts, the agent step and the approval wait. A step that **ran** and failed, was blocked or was skipped MUST have error status, or an explicit status attribute, with a pt-BR reason. A step that never started (because an upstream step failed) produces no span. The run's root span ends in the failed state, and the orchestrator shows the steps that didn't run.
- **FR-005**: A run's pipeline spans and its agent decision trace MUST be linked so that each is reachable from the other in at most two navigation steps (SC-003).

**Exploring traces (Block 4)**

- **FR-006**: The trace service MUST show, for any agent trace, the full span tree with every attribute, event, status and error message the default track's trace HTML shows for the same span.
- **FR-007**: The orchestrator's view of each run and each approval request MUST link to the corresponding trace in the trace service. A run without an agent trace (duplicate skip, agent not reached) MUST say why.
- **FR-008**: Approval decisions (approve, reject, expiry) and rollbacks MUST appear as spans linked to the original request or change and to its decision trace.
- **FR-009**: The trace service and the guide MUST be enough to answer the three Block 4 auditor questions (`docs/02-exercicios.md`, Bloco 4, exercise 1) without the terminal.

**Parity and audit**

- **FR-010**: The parity check MUST also compare the agent's traces between the tracks for the same scenario and reference time: same span names, same tree shape, same decision attributes and statuses, ignoring ids, timestamps and durations. It MUST list every difference.
- **FR-011**: The stack track MUST keep a tamper-evident audit record of every agent decision, approval, expiry and rollback, with a verify command that reports intact/broken and identifies the first broken record. The existing hash-chained log, written by the shared tracing code, stays the record of truth on the stack. Spans are **also** exported to the trace service, which is the exploration view and is not what the verify command checks. The guide MUST document this as a partial replacement of `tracing.py`.
- **FR-012**: If the trace service is unavailable, the agent's executed decisions MUST still reach the audit record (they do, because the hash-chained log is written independently of the export). A run MUST NOT fail or wait because the trace service is down, and spans produced while it is down MUST NOT be silently lost: they are delivered when it returns, or a pt-BR warning in the run says which spans exist only in the audit record.

**Dashboards**

- **FR-013**: Phase 3 MUST NOT add a separate dashboard tool. The trace service's own views (search, span tree, error filtering) are the only new visual surface.
- **FR-014**: The roadmap in the guide MUST remove the dashboard tool from Phase 3, with the reason: it doesn't name a module it replaces (Principle VI). A later proposal can add it back if it names one.
- **FR-015**: Any status the stack's own spans show for missing or blocked data (e.g., a blocked batch, a failed verdict) MUST read as unknown or blocked, never as zero or success (Principle III). The agent's spans are unchanged and keep the default track's representation (e.g., a stale feed in `data.stale_sources`, a refusal as `sem_dados`).

**Constraints and documentation**

- **FR-016**: The default track MUST stay unchanged and keep working with no containers. Its optional Phoenix exercise (`docs/02-exercicios.md`, 4.5) still works. The existing default-track suite MUST pass unchanged (Principle V).
- **FR-017**: After the images are pulled or built once, the stack track MUST run offline. Usage telemetry of every added tool MUST be off.
- **FR-018**: The stack track MUST have automated tests for each Phase 3 promise: the agent trace reaches the trace store with its full span tree; pipeline spans exist and link to the agent trace; a blocked batch is an error span; approval and rollback spans link back; the stack's verify command detects tampering; the run survives a trace-service outage without losing decisions.
- **FR-019**: The guide (pt-BR) MUST update the replacement map with every Phase 3 tool, the module it replaces, the block, and any partial replacement. It MUST also update "Lacunas conhecidas" (remove the traces gap, add any new honest gaps, including that the hash-chained log stays the audit record), the roadmap (Phase 3 done, dashboard tool removed per FR-014), prerequisites (host resources, the new URLs) and the new commands.
- **FR-020**: The instructor script MUST get a stack-track runbook for Block 4 (and the trace part of Block 5 triage) that matches the default-track teaching points.
- **FR-021**: The stack's minimum host requirement MUST stay at 8 GB of free RAM. Any added service that would push the measured peak of a full run above what 8 GB supports MUST be justified in the plan's Complexity Tracking.

### Key Entities

- **Trace**: one tree of spans with a `trace_id`. An **agent decision trace** covers one agent run (`agent.run` root). A **pipeline run trace** covers one orchestrator run. The two are linked (FR-005).
- **Span**: a named step with start, end, status (ok/error/skipped), attributes, events and an optional link to another trace or span. Agent span names and attributes are fixed by the shared agent code.
- **Run**: one orchestrator execution of the daily pipeline for a business date, with a run id, optional incident and the agent-run status (`done`, `skipped_duplicate`, not reached).
- **Approval request / decision**: an agent action above its autonomy level, queued for a human. It is created inside an agent trace and decided (or expired) later in its own span, linked back.
- **Audit record**: the tamper-evident, hash-chained sequence of decision, approval, expiry and rollback records, with a verify result (intact / broken at record N). It is the record of truth. The trace store holds a copy for exploration.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A participant who hasn't seen the trace service answers all three Block 4 auditor questions from the trace service alone in **≤ 5 minutes** (timed in a dry run).
- **SC-002**: For every scenario (no incident and each of the four incidents), the trace parity check reports **zero differences** between the tracks' agent traces, ignoring ids and timing.
- **SC-003**: From an approval request to its decision trace, and from an agent decision trace to the pipeline run that fed it, takes **≤ 2 navigation steps** each.
- **SC-004**: An agent trace is searchable in the trace service **≤ 30 seconds** after the agent step finishes.
- **SC-005**: With the trace service stopped during a run, **100%** of the agent's executed decisions are in the audit record afterwards, and the run finishes with the same status as with the service up.
- **SC-006**: Editing any single stored decision value is detected by the verify command in **100%** of trials, which name the altered record.
- **SC-007**: The measured peak memory of all stack containers during a full run stays **within the 8 GB host minimum** (Phase 2 measured 2.6 GB). The guide records the new peak.
- **SC-008**: The default-track test suite passes **unchanged**, and every Phase 3 promise in FR-018 has a test that fails when the promise breaks.
- **SC-009**: In a Block 5 dry run on the stack, squads reach the decisions made on bad data via the trace service **no slower** than with the default track's `trace last` / `lineage --since`.

## Assumptions

- **Tool choices come from the Phase 1 roadmap** (`stack/README.md`, spec 001 FR-025) and are recorded here for planning: an **OpenTelemetry Collector** for collection; **Arize Phoenix** as the trace store and viewer, chosen over Langfuse because it runs as a single service that accepts OTLP directly, can reuse the stack's existing database, and is the tool the default track's optional Block 4 exercise already points to. Langfuse v3 needs several extra services (an analytics database, a cache and object storage), which threatens the 8 GB minimum (FR-021). The planning phase confirms this choice. The spec states behavior, so either can be swapped. **Grafana is out** (FR-013, FR-014).
- **Pipeline spans** come from the orchestrator and transformation tools' own tracing support where it exists, and from thin stack-side wrappers where it doesn't. The planning phase decides the mix and documents it as a partial replacement if needed.
- **Linking** a pipeline run to an agent trace may use the same trace or a span link. Either satisfies FR-005 as long as SC-003 holds. The agent's `trace_id` already reaches the orchestrator run and the lineage facet (Phase 2), and Phase 3 reuses it.
- **Retention**: stored traces are kept until `make reset`. Block 4's "≥ 6 months for high-risk systems" (EU AI Act, art. 19/26(6)) stays a good-practice talking point, not a stack setting (Principle VII: our case is probably not high-risk).
- **Rules brain by default**. Model-call spans only appear when the optional Claude brain is used (Principle IV).
- **Users and access**: same local-study accounts as Phases 1–2. The trace service runs without authentication on localhost and are documented as local-only.
- **Out of scope for Phase 3**: Phase 4 (mock APIs with declarative ingestion; policy-as-code guardrails; snapshot table format) and Phase 5 (metadata catalog). Agent decision logic is unchanged (Principle I). Dashboards, metrics stores and log pipelines are out of scope.
