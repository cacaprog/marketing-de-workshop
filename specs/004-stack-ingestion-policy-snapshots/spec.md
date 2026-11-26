# Feature Specification: Stack Track Phase 4 — Live Ingestion, Policy as Code and Snapshots

**Feature Branch**: `004-stack-ingestion-policy-snapshots`

**Created**: 2026-11-25

**Status**: Draft

**Input**: User description: "phase 4". This is the next phase of the stack-track roadmap defined in `specs/001-stack-production-track/spec.md` (FR-025) and `stack/README.md` ("Roteiro das próximas fases"). Phase 4 has three parts: **mock upstream APIs that fail realistically, with a declarative ingestion tool** (replaces the static scenario load in `generate.py`, Block 1); **policy-as-code guardrails** (replaces how `config/guardrails.yaml` is enforced, Block 3); **a table format with snapshots** (replaces the single warehouse file, Block 5).

## Context

Phases 1–3 (`specs/001`–`003`) moved the daily Aurora media run onto production tools: an orchestrator, a transformation framework, contract validation, human approvals, data observability, lineage and traces. Three parts of the stack track still don't look like production. Each one is hand-written and shared with the default track:

1. **Data doesn't arrive. It's written into Bronze.** The shared generator (`generate.py`) writes all 30 days of the scenario into the Bronze tables in one step. The planted problems are already there: the stalled Meta feed, the duplicated ga4 batch, sparse dirty rows and the broken old batch. Block 5 incidents (`incidents.py`) edit Bronze rows directly. No source system exists to fail, time out, page, retry or redeliver. Lineage shows the ga4 feed only as `bronze.conversions` (a known gap in `stack/README.md`: "sem nó por fonte até a Fase 4").
2. **Guardrails are YAML read inside the agent's capabilities.** The limits in `config/guardrails.yaml` (±20% per action, 2 changes per campaign per day, the portfolio cap, the minimum budget, eligible objectives, fresh sources) are compared in Python inside `capabilities.py` (`_common_checks`, `budget_checks`). Nobody can test, review or version the policy apart from the code that runs it, and nothing outside the agent process can answer "would this action be allowed?".
3. **The warehouse is a single file with no history.** All layers and the live campaign state live in one embedded database file. Rolling back an incident means restoring a hand-made backup copy of one batch (`meta.incident_backup` in `incidents.resolve`). Nobody can ask "what did Gold look like when the agent decided?".

Phase 4 closes these gaps. It applies the same rule as Phases 1–3: **a tool joins the stack only if it replaces an existing module** (Principle VI).

| Capability | Replaces (default track) | Block |
|---|---|---|
| Mock upstream sources (ad platform, ga4, Meta Conversions API) served over the network, failing like real ones | the Bronze writes in `generate.py` (`generate()`, `backfill_meta()`) and the Bronze edits in `incidents.inject()` / `resolve()` | 1, 5 |
| Declarative ingestion from those sources into Bronze, with per-source batches, state and load records | the static scenario load (`generate.py` → `_bulk_insert`) and the stack's `ingest` task | 1 |
| Guardrails as a versioned, testable policy, evaluated by a policy engine | the enforcement of `config/guardrails.yaml` in `capabilities.py` (`_common_checks`, `budget_checks`), through a replaceable policy evaluator in the shared code (FR-015) | 3 |
| A table format with snapshots for the data layers | the single warehouse file (`db.py`, `AGENTREADY_DB`) and the hand-made incident backup (`meta.incident_backup`) | 5 |

The Block 1, 3 and 5 lessons stay the same, and the stack can now teach them with production tools: **bad data arrives from outside and the architecture has to catch it at the door; guardrails are a policy that lives outside the model; a mistake in the data is undone by going back to a known-good version, not by hand.**

## Clarifications

### Session 2026-11-26

- Q: Where does the policy engine plug in, given that the guardrail checks live in the shared `capabilities.py` and Principle I requires one agent source? → A: The shared capabilities get one replaceable policy evaluator. The default track evaluates in-process from the YAML, and the stack asks the policy engine. An automated equivalence check proves both give identical verdicts (Option A; FR-015, FR-015a).
- Analysis 2026-11-26: FR-019 was narrowed to the default track's behavior, and the allowed shared edits are listed in plan.md. FR-008 names snapshots per pipeline stage (ingestion snapshots also name their batches). The policy engine being down before the agent step now refuses the step (edge case, SC-007).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Data arrives from failing upstream sources (Priority: P1)

The instructor starts a daily run on the stack. Instead of a script writing Bronze, the run pulls each feed from its mock source system (ad platform spend, ga4 conversions, Meta Conversions API) through a declarative ingestion step. The sources behave like real ones. Meta is stalled (its token expired three days ago), ga4 redelivers a batch it already sent, a few rows are dirty, and an old batch carries an upstream bug. Some requests fail now and then and are retried. Every planted problem still reaches Bronze exactly as before, so Block 1's contracts, quarantine and circuit breaker catch them. Block 5 incidents are now upstream behaviors (a source starts sending cents, renames a field, redelivers yesterday, stops delivering) and no longer edits to Bronze.

**Why this priority**: This is the most visible realism gain ("lotes atrasados, duplicados e quebrados chegando como na vida real"). It also closes the per-source lineage gap left open since Phase 2. The other two stories are useful without it, but this one changes how every block's data is born.

**Independent Test**: Reset the scenario and trigger one daily run with no incident. Confirm that Bronze is filled only by the ingestion step, from the mock sources. Confirm that each planted problem appears in Bronze with the same batch ids and row counts as the default track's generator. Confirm that the parity check reports zero differences in Gold, source health and the agent's decisions.

**Acceptance Scenarios**:

1. **Given** a reset stack scenario, **When** the daily run's ingestion step runs, **Then** each feed is loaded from its own source and recorded per source and batch (rows, when, which request). Bronze has the same rows the default track's generator writes for the same scenario and reference time.
2. **Given** the default scenario, **When** ingestion asks the Meta source for the last three days, **Then** the source answers that there is no new data. The feed is stale in source health, and the agent refuses to act on Meta campaigns (`sem_dados`), as on the default track.
3. **Given** the duplicated ga4 batch, **When** it is ingested, **Then** both deliveries land in Bronze (the ingestion step doesn't dedupe the business data), and the contract stage blocks the duplicate as it does today. Block 1's lesson is not hidden by the tool.
4. **Given** a source that returns a transient error (e.g., timeout or "try again later") on the first request, **When** ingestion retries, **Then** the batch is loaded once. A retry by the ingestion step never creates a duplicate batch. Only an upstream redelivery does, as in scenario 3.
5. **Given** the "Meta backfill" run parameter, **When** the run ingests, **Then** the Meta source now delivers its held batches, the feed becomes fresh, and the result matches the default track's `backfill_meta`.
6. **Given** each Block 5 incident (`centavos`, `renomeacao`, `lote_duplicado`, `feed_parado`), **When** the instructor injects it, **Then** the change happens in the mock source's behavior for yesterday's ga4 batch, the next ingestion brings it into Bronze, and the contract and observability stages react exactly as they do today.
7. **Given** a finished run, **When** the user opens lineage, **Then** each source feed is its own node upstream of Bronze. The ga4 feed is no longer shown only as `bronze.conversions`.

---

### User Story 2 - Undo a bad batch by going back to a snapshot (Priority: P2)

During Block 5 a squad finds the `centavos` incident: the agent decided on data that was 100× too large. To resolve it, the instructor doesn't restore a hand-made backup. They go back to the data layers' last known-good version (the snapshot taken before the bad batch arrived), re-run the downstream layers, and show "what Gold looked like when the agent decided" next to "what it looks like now". Rolling back the agent's own budget changes still goes through the change log, as on every track.

**Why this priority**: This turns the Block 5 recovery story into the production practice: *time travel* in place of a backup copy. It comes after P1 because the most useful snapshots are the ones taken at each ingestion.

**Independent Test**: Run the daily pipeline twice, the second time with `centavos`. List the snapshots and identify the one before the incident batch. Query Gold as of that snapshot and as of now. Resolve the incident by restoring the data layers to that snapshot. Confirm that Gold and source health match a clean run, and that the incident's TTR is recorded.

**Acceptance Scenarios**:

1. **Given** several finished runs, **When** the user lists snapshots, **Then** each data-layer snapshot shows when it was taken, which run and ingestion batch produced it, and the incident open at the time, if any.
2. **Given** an agent decision in the audit record, **When** the user asks for Gold as of that decision, **Then** they get the campaign×day rows the agent read, and the metric the decision cites matches the span attribute in its trace.
3. **Given** an open `centavos` incident, **When** the instructor resolves it, **Then** the data layers return to the snapshot before the bad batch, without any hand-made backup. The incident closes with TTD/TTR as today, and the restore is recorded (who, when, from which snapshot to which).
4. **Given** a restore to an earlier snapshot, **When** the user lists snapshots again, **Then** the later snapshots are still there (the restore is itself a new version, not a deletion), so the restore can be undone.
5. **Given** an agent budget change made on the bad data, **When** the instructor rolls it back, **Then** rollback uses the change log, as on the default track. Snapshots of the data layers never change the live campaign state.

---

### User Story 3 - Guardrails as a policy anyone can test (Priority: P3)

The Block 3 instructor opens the guardrail policy: a versioned file with the rules (±20%, 2 changes a day, portfolio cap, minimum budget, eligible objectives, fresh sources) and tests next to it. They show that the policy engine, not the agent, says whether an action is allowed, and that the same check ids and pt-BR reasons appear in the agent's trace as today. They change one limit in a copy, run the policy tests, and show one failing. Then they ask the engine directly "would raising C01 by 30% be allowed?" and get "no, `variacao_maxima`" without running the agent.

**Why this priority**: This makes Principle II ("safety lives in the backend") visible as a separate, reviewable artifact. It is P3 because the Block 3 lesson already works today, and this story only changes where the rules are evaluated.

**Independent Test**: Run the policy's own test suite. Run the agent on the default scenario and on the `gullible` (prompt-injection) scenario. Confirm that every precondition check has the same id, verdict and pt-BR detail as on the default track, and that the parity check reports zero decision differences.

**Acceptance Scenarios**:

1. **Given** the policy and its tests, **When** the user runs the policy tests, **Then** each guardrail in `config/guardrails.yaml` has at least one allow case and one deny case, and all pass.
2. **Given** a proposed action, **When** the user asks the policy engine about it directly (outside any agent run), **Then** it answers allowed or denied, with the ids of the failed checks and their pt-BR reasons.
3. **Given** a daily run, **When** the agent proposes an action, **Then** the verdict comes from the policy engine, and the trace shows the same check ids, verdicts and details as the default track for the same scenario, plus the policy version that decided.
4. **Given** the `gullible` scenario (a briefing tells the agent the cap was raised), **When** the agent proposes the larger change, **Then** the policy engine denies it with `variacao_maxima` / `teto_do_portfolio`, as today. Text never changes the policy.
5. **Given** the policy engine is unreachable, **When** the agent proposes a write action, **Then** the action is denied (fail closed), with a pt-BR reason saying the policy could not be evaluated. Nothing is executed and the run doesn't hang.
6. **Given** an approved request executed hours later, **When** it runs, **Then** the policy is evaluated again against the live state (Principle II), as today.

---

### User Story 4 - The guide and instructor script cover Phase 4 (Priority: P3)

A reader of the stack guide sees each new tool in the replacement map, with the module it replaces and the block it supports, and any partial replacement. "Lacunas conhecidas" drops the per-source lineage gap and adds any new honest gaps. The roadmap shows Phase 4 as done. The instructor script explains how to run Blocks 1, 3 and 5 with the new pieces: where the sources are, how to show the policy and its tests, how to list and restore snapshots.

**Why this priority**: Phases 1–3 set this documentation pattern. Without it the instructor can't present Phase 4 truthfully. It ships last because it describes the finished behavior.

**Independent Test**: A person who hasn't seen Phase 4 follows the guide from a clean checkout to (a) a run fed by the mock sources, (b) a policy-test failure after editing one limit in a copy, and (c) an incident resolved by restoring a snapshot.

**Acceptance Scenarios**:

1. **Given** the stack guide, **When** a reader looks up any Phase 4 tool, **Then** the replacement map names the module it replaces and the block it supports, and notes any partial replacement.
2. **Given** the instructor script, **When** the instructor prepares Blocks 1, 3 or 5, **Then** each has a stack-track note: what to open, what to show, and what the audience should see.

---

### Edge Cases

- **A source down for the whole run** (not a transient error): ingestion records the feed as not delivered with a pt-BR reason. The run continues with the other feeds. Source health shows the feed as stale, never as zero (Principle III).
- **A source that keeps failing after retries**: the batch is recorded as failed, not partly loaded. The next run picks it up again without duplicating what already landed.
- **Partial page** (a source returns some pages and then fails): no partial batch reaches the contract stage as if it were complete.
- **Schema change at the source** (`renomeacao`): ingestion must not "fix" it by mapping the new column back. The raw table shows the change, and the contract stage treats it as a schema violation, as today.
- **Ingestion re-run on the same day with nothing new**: no new batch, no new snapshot of changed data, and the agent's duplicate-run guard still applies.
- **Policy file invalid or missing, or the policy engine down before the agent step**: the stack refuses to run the agent step (fail closed), with a pt-BR message, as it does today for an invalid contract. If the engine goes down while the agent runs, each write still in flight is denied (FR-016).
- **Policy version vs. guardrails version**: every decision trace records the policy version. A policy whose limits differ from `config/guardrails.yaml` is a parity difference, never a silent change.
- **Restore while a run is active**: refused with a pt-BR message. Only one writer at a time (Phase 1 FR-007 still holds).
- **Restore to a snapshot before the scenario's reset**: refused or clearly warned, since the live campaign state wouldn't match.
- **Snapshot growth**: every run adds snapshots. The guide says how much disk a workshop day uses, and `make reset` clears them all and never touches the default track's `data/`.
- **Clock and time zone**: snapshot and batch times show in the instructor's local time. Business dates stay America/Sao_Paulo.

## Requirements *(mandatory)*

### Functional Requirements

**Mock sources and ingestion (Block 1)**

- **FR-001**: The stack track MUST run mock upstream sources for each feed in the scenario (ad platform spend, ga4 conversions, Meta Conversions API, campaign catalog). They MUST serve the data of the shared, deterministic scenario. The scenario's rows, batches and planted problems MUST come from the shared generator, not from a copy (Principle I, shared sources).
- **FR-002**: The mock sources MUST be able to fail like real ones: no data yet (stalled feed), redelivered batch, dirty rows, broken batch, renamed field, values in the wrong unit, transient errors (timeouts and "try again later"), and pagination. Every failure MUST be deterministic for a given scenario, reference time and run parameter, so the demo is the same every time (Principle IV).
- **FR-003**: A declarative ingestion step MUST load every feed from its source into Bronze, recording per source and batch: rows loaded, request time, status (loaded, no new data, failed) and the reason in pt-BR. The stack's current Bronze write in the `ingest` task MUST be replaced by it.
- **FR-004**: Ingestion MUST be idempotent for its own retries (a retried request never duplicates a batch), and MUST NOT dedupe, repair, rename or retype business data. Every planted problem and incident MUST reach Bronze as the source sent it, so the contract stage is still what catches it.
- **FR-005**: For the default scenario and each documented run parameter (reset, Meta backfill, each incident), Bronze after ingestion MUST give the same Gold, source health and agent decisions as the default track. The parity check MUST report zero differences (Principle V).
- **FR-006**: Block 5 incidents on the stack MUST be injected and resolved at the mock source (a change in what the source sends), not by editing Bronze. The incident log (kind, injected, detected, resolved, TTD, TTR) MUST work as today.
- **FR-007**: Lineage MUST show each source feed as its own node upstream of Bronze, closing the gap recorded in `stack/README.md`.

**Snapshots and time travel (Block 5)**

- **FR-008**: The data layers (Bronze, quarantine, Silver, Gold, metadata) MUST be stored in a table format that keeps snapshots. Every ingestion and every pipeline stage (contracts, Gold + observability, the agent's read) MUST produce a named snapshot. Ingestion snapshots name their run and batches; stage snapshots name their run.
- **FR-009**: The user MUST be able to list snapshots, and to query any data layer as of a snapshot or a point in time, from the guide's commands. For any agent decision in the audit record, the user MUST be able to get the Gold rows as of that decision.
- **FR-010**: Resolving a Block 5 incident on the stack MUST restore the affected data layers to the snapshot before the bad batch, with no hand-made backup copy. The restore MUST be recorded (who, when, from which snapshot to which) and MUST itself be undoable.
- **FR-011**: The live campaign state, the change log, the approval queue and the agent-run ledger MUST keep working as today. Rollback of agent actions MUST still use the change log (Principle II). A data-layer restore MUST never change the live campaign state.
- **FR-012**: Only one writer at a time MUST still hold (Phase 1 FR-007). A restore during an active run MUST be refused.

**Policy as code (Block 3)**

- **FR-013**: Guardrail rules MUST live in a versioned policy, with automated tests, evaluated by a policy engine. The limits stay in `config/guardrails.yaml` (shared business configuration). The policy reads them and doesn't copy them.
- **FR-014**: The policy MUST produce, for each proposed action, the same check ids, verdicts and pt-BR details the agent's precondition checks produce today (`campanha_existe`, `campanha_ativa`, `sem_trava_humana`, `objetivo_elegivel`, `justificativa_presente`, `dados_frescos`, `variacao_maxima`, `orcamento_minimo`, `teto_do_portfolio`, `limite_de_alteracoes`), so the agent's traces and decisions don't change between tracks (Principle I). Each decision trace MUST record the policy version.
- **FR-015**: On the stack, write actions MUST be allowed or denied by the policy engine, both when the agent proposes them and when an approved request is executed later. The shared capabilities MUST call one replaceable **policy evaluator** to evaluate the guardrail checks. The default track's evaluator runs in-process from `config/guardrails.yaml` (no containers, Principle IV). The stack's evaluator asks the policy engine. Only the source of the verdict changes. The capabilities' decision flow (preconditions → autonomy ladder → execution) and the agent's decision rules don't change (Principle I). The plan MUST justify this one structural change to shared code in Complexity Tracking.
- **FR-015a**: An automated equivalence check MUST run both evaluators on the same set of proposed actions and live states (at least every allow and deny case from FR-018, plus every action in the parity scenarios). It MUST report every difference in check id, verdict or detail. Any difference is a defect, and the check runs in `make test` and as part of the parity check.
- **FR-016**: If the policy engine can't be reached or the policy is invalid, write actions MUST be denied (fail closed) with a pt-BR reason. The run MUST NOT hang. Read-only steps and refusals keep working.
- **FR-017**: The policy engine MUST answer "would this action be allowed?" for a given action and live state, outside any agent run, from a guide command.
- **FR-018**: Every guardrail MUST have at least one allow test and one deny test in the policy's test suite. The suite runs in `make test`.

**Constraints and documentation**

- **FR-019**: The default track's **behavior** MUST stay unchanged. It keeps working with no containers, no network and no API key (Principle IV), and its existing tests MUST pass **without edits** (Principle V). The only shared-code changes allowed are those plan.md lists in Complexity Tracking: the policy evaluator (FR-015) and extracting the live-state table creation and seeding in the shared generator. Neither may change what the default track writes, decides or traces, apart from the two added `policy.*` span attributes.
- **FR-020**: After images are pulled or built once, the stack MUST run offline. Usage telemetry of every added tool MUST be off. No mock source is reachable from outside the host.
- **FR-021**: The stack MUST have automated tests for each Phase 4 promise: feeds come only from the sources; each planted problem reaches Bronze unchanged; ingestion retries don't duplicate; each incident works through its source; snapshots are listed and queried as of a decision; incident resolve restores a snapshot and is undoable; the policy gives the same checks as today; the policy fails closed.
- **FR-022**: The parity check MUST keep passing for every scenario it covers today, with zero differences in Gold, source health, agent decisions, observability verdicts and agent traces.
- **FR-023**: The guide (pt-BR) MUST update the replacement map with every Phase 4 tool, the module it replaces, the block and any partial replacement. It MUST also update "Lacunas conhecidas" (remove the per-source lineage gap, add new honest gaps), the roadmap (Phase 4 done), prerequisites (host resources, new URLs) and the new commands.
- **FR-024**: The instructor script MUST get stack-track notes for Blocks 1, 3 and 5 that match the default-track teaching points.
- **FR-025**: The stack's minimum host requirement MUST stay at 8 GB of free RAM (Phase 3 measured peak: 3.0 GB). Any added service that would push the measured peak above what 8 GB supports MUST be justified in the plan's Complexity Tracking.

### Key Entities

- **Mock source**: a stand-in for an upstream system (ad platform, ga4, Meta Conversions API, campaign catalog). It serves the shared scenario's data for a feed, with its current failure behavior (none, stalled, redelivery, cents, renamed field, transient errors).
- **Ingestion load**: one attempt to pull one feed for one batch: source, batch id, request time, rows, status (loaded / no new data / failed), reason, retries. It is what lineage shows upstream of Bronze.
- **Snapshot**: a version of the data layers, with when it was taken, the run and batch that produced it, and the incident open at the time.
- **Restore**: a recorded move of the data layers to an earlier snapshot (who, when, from, to). It creates a new version and can be undone.
- **Guardrail policy**: the versioned rules plus their tests. It reads the limits from `config/guardrails.yaml` and returns allowed/denied with the check list (id, verdict, pt-BR detail).
- **Policy decision**: the engine's answer for one proposed action against the live state, recorded in the action's span with the policy version.
- **Incident** (existing): now injected and resolved at a mock source, and resolved by a snapshot restore. TTD/TTR as today.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: The parity check reports **zero differences** between the tracks for every scenario it covers today (default morning, post-backfill, supervised autonomy, and each of the four incidents).
- **SC-002**: **100%** of the generator's planted problems (stalled Meta, duplicated ga4 batch, dirty rows, broken old batch) reach Bronze through ingestion and are caught by the contract stage, with the same quarantine counts and blocked batches as the default track.
- **SC-003**: With a transient source error forced on every feed, a run finishes with **0 duplicate batches** caused by ingestion retries.
- **SC-004**: A Block 5 incident is resolved by a snapshot restore in **≤ 2 commands**, and Gold and source health afterwards match a clean run **exactly**.
- **SC-005**: For any agent decision, the Gold rows as of that decision are retrieved in **≤ 1 command**, and the cited metric matches the decision's trace in **100%** of trials.
- **SC-006**: Every guardrail has **≥ 1 allow and ≥ 1 deny** policy test. Changing any single limit in a copy makes **≥ 1** test fail.
- **SC-006a**: The evaluator equivalence check (FR-015a) reports **zero differences** between the in-process evaluator and the policy engine.
- **SC-007**: With the policy engine stopped, **0** write actions are executed: the agent step is refused before it runs, or each in-flight write is denied, and nothing hangs.
- **SC-008**: The measured peak memory of all stack containers during a full run stays **within the 8 GB host minimum**. The guide records the new peak.
- **SC-009**: The default-track test suite passes **unchanged**, and every Phase 4 promise in FR-021 has a test that fails when the promise breaks.
- **SC-010**: In a dry run, a person who hasn't seen Phase 4 resolves a `centavos` incident by snapshot restore, following only the guide, in **≤ 10 minutes**.

## Assumptions

- **Tool choices come from the roadmap** in `stack/README.md` and are recorded here for planning. **Mock sources**: a small HTTP service per source family. **Declarative ingestion**: dlt. **Policy engine**: Open Policy Agent. **Table format**: DuckLake or Apache Iceberg. The planning phase chooses one and confirms its fit with dbt-duckdb, the stack's single-writer rule and the 8 GB minimum. If object storage is needed, the plan checks that the chosen store still publishes community releases and container images, since availability has changed for some projects (Principle VII). The spec states behavior, so tools can be swapped as long as each names the module it replaces (Principle VI).
- **The shared generator stays the scenario's source of truth.** The mock sources serve what it produces. The default track keeps writing Bronze directly. The plan decides how the generator exposes the data without writing Bronze, without changing the default track's behavior.
- **What the snapshots cover**: the data layers only (Bronze, quarantine, Silver, Gold, metadata). The live campaign state, change log, approval queue, incident log and agent-run ledger are operational state. They stay as today and are rolled back through the change log, not through time travel (FR-011). The plan decides where the operational state lives if the table format can't hold it as today (e.g., primary keys).
- **Block 5 parity**: on the default track, incidents keep editing Bronze directly. Only the stack moves them to the source. Both tracks MUST end with the same Bronze rows, so parity still holds.
- **Ingestion run times**: the source "arrival time" of each batch keeps the scenario's timeline (e.g., ga4 loaded ~3 h after the day ends), so freshness and SLAs give the same answers as the default track.
- **Users and access**: same local-study accounts as Phases 1–3. The mock sources, the policy engine and any object store run on the stack's internal network without host ports, except where the guide shows them to the audience. All are documented as local-only.
- **Rules brain by default**. The Claude brain stays opt-in (Principle IV).
- **Out of scope for Phase 4**: Phase 5 (metadata catalog). Changing the agent's decision rules (Principle I). Real upstream APIs or credentials. Streaming ingestion. Multi-writer concurrency. Moving the MCP server or semantic layer.
