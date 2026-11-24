# Feature Specification: Stack Track — Production-Shaped Version of the Workshop (Phase 1)

**Feature Branch**: `001-stack-production-track`

**Created**: 2026-11-24

**Status**: Draft

**Input**: User description: "Stack version of the agentready workshop that runs separately from the default zero-Docker demo: a `stack/` folder with Docker Compose that replaces hand-rolled modules with production open-source tools while keeping the agent's decision logic unchanged. Phase 1 scope: Airflow 3 + Postgres, dbt-core + dbt-duckdb rebuilding Bronze/Silver/Gold, astronomer-cosmos to render dbt in Airflow, one DAG (ingest → ODCS contract checks via datacontract-cli with circuit breaker → silver → gold → agent run → human-in-the-loop approval). Later phases (out of scope for phase 1 but roadmap): OpenLineage + Marquez, Elementary anomaly detection (catches the centavos incident that passes the contract), OTel Collector + Phoenix/Langfuse + Grafana, mock upstream APIs + dlt, OPA guardrails, DuckLake/MinIO time travel, OpenMetadata. Rule: every tool must replace an existing module."

## Context

The workshop "Construindo Dados Prontos para IA Agêntica" teaches, in Blocks 0–5, that **the agent's decision logic doesn't change; the data architecture around it does.** In the current version, every architecture layer (pipeline, contracts, quarantine, circuit breaker, freshness SLA, approval queue) is hand-written so the audience can read all of it, and it runs with no containers, no cloud and no API key.

The **stack track** is a second way to run the same scenario (Aurora Cosméticos, 6 campaigns, the same corrupted feeds). The hand-written layers are swapped for the standard open-source tools that data teams run in production. It adds a second message to the workshop: *"…and this is how you'd run it in production."* It doesn't replace the default demo.

**Governing rule (applies to this phase and every later one):** a tool joins the stack only if it **replaces an existing module** of the default track. If no module can be named, the tool is out of scope.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Run the daily media pipeline end-to-end on the stack (Priority: P1)

An instructor (or a data engineer studying the project) starts the stack with one documented command. They open the orchestrator's web UI and trigger the daily "Aurora media" run. They watch each stage in order: ingest the raw feeds, check them against the data contracts, build the cleaned layer, build the business-ready layer, run the agent, and route the agent's risky actions to a human. Each stage shows its status, its logs and how long it took.

**Why this priority**: This is the minimum viable stack track. Without a visible, scheduled, end-to-end run, none of the other stories have anything to show.

**Independent Test**: On a clean machine with only the documented prerequisites, start the stack, trigger one run, and confirm that every stage finishes (or stops on purpose, per Story 3) and the agent's report is visible.

**Acceptance Scenarios**:

1. **Given** a machine with the documented prerequisites and the stack not running, **When** the user runs the documented start command, **Then** all services become healthy and the orchestrator UI is reachable at a documented local address, with no manual setup steps.
2. **Given** the stack is running and the scenario has been generated, **When** the user triggers the daily run, **Then** the stages run in this order: ingest → contract checks → cleaned layer → business layer → agent → approval, and each one is shown as a separate, inspectable step.
3. **Given** a finished run, **When** the user opens the agent step, **Then** they see the same narrated decision report the default track prints: what data it read, which checks passed or failed, and which actions it executed, queued or refused.
4. **Given** a finished run, **When** the user triggers it again with no data changes, **Then** it produces the same business-layer results and no duplicate budget changes (the run is idempotent).

---

### User Story 2 - Prove the agent is unchanged: parity with the default track (Priority: P2)

The instructor runs the same scenario on both tracks and compares them. The business-layer numbers, the data-health signals and the agent's decisions are identical. This proves on stage that only the infrastructure changed.

**Why this priority**: Parity is what makes the stack track teach something instead of being a second, separate project. It also protects the workshop's central claim.

**Independent Test**: Generate the scenario with a fixed reference time, run both tracks, and run a documented comparison that reports any difference.

**Acceptance Scenarios**:

1. **Given** the same generated scenario and the same reference time, **When** both tracks have run, **Then** the per-campaign daily business table matches row for row: spend, orders, gross revenue and discounts.
2. **Given** the same inputs, **When** both tracks have run, **Then** the data-health table reports the same freshness status (fresh/stale) for each feed and partition, including the Meta feed that is 3 days stale.
3. **Given** the same inputs and the same autonomy configuration, **When** both agents have run, **Then** they produce the same set of actions with the same outcomes (executed, sent for approval, refused) and the same reasons.
4. **Given** a difference exists, **When** the comparison runs, **Then** it names the table or decision that differs and shows both values.

---

### User Story 3 - Contracts and circuit breaker stop bad data before the agent sees it (Priority: P3)

A data engineer runs the morning scenario, which includes a duplicated batch, negative values and a stale Meta feed. The contract-check stage quarantines bad rows one by one. Any batch whose quarantine rate goes over the contract's limit is blocked as a whole. The engineer can see in the orchestrator exactly which batches were blocked and why. The business layer reports missing data as unknown, never as zero.

**Why this priority**: This is Block 1's lesson, now run by production tools. It's the most important safety behavior for the agent.

**Independent Test**: Run the pipeline on the default morning scenario and check the quarantine contents, the batch status records and the business layer, without running the agent.

**Acceptance Scenarios**:

1. **Given** a raw batch containing rows that break the contract, **When** the contract stage runs, **Then** those rows go to quarantine together with the reasons they failed, and the valid rows continue to the cleaned layer.
2. **Given** a batch whose quarantine rate is above the contract's limit, **When** the contract stage runs, **Then** the whole batch is blocked. None of its rows reach the cleaned layer, and the block is recorded with its rate and the limit.
3. **Given** a raw table that is missing a column the contract requires, **When** the contract stage runs, **Then** the cleaned layer keeps its last good state. The run shows a schema violation, and the freshness check later reports the feed as stale.
4. **Given** a feed whose last successful load is older than its SLA, **When** the business layer is built, **Then** the health table marks it stale, and the agent refuses to act on the campaigns that depend on it.
5. **Given** a blocked batch or a schema violation, **When** the operator looks at the run, **Then** the stage is visibly marked as needing attention (not silently green), and the steps after it run with the last good data only.

---

### User Story 4 - A human approves or rejects agent actions inside the orchestrator (Priority: P4)

When the agent proposes an action that the autonomy ladder routes to a human, for example a budget change above 10% or any campaign pause, the run waits for a decision. An approver sees the proposed action, the agent's justification and the checks it passed. They approve or reject it in the orchestrator UI. Only an approved action is applied, and the decision is recorded with the approver's identity.

**Why this priority**: This is Block 4's approval queue, moved to the place where operators actually work. It's valuable, but it depends on Stories 1–3 producing trustworthy decisions first.

**Independent Test**: Run with the autonomy override set to "supervised". Confirm that every action waits for approval, then approve one and reject another, and check the live campaign state and the change log.

**Acceptance Scenarios**:

1. **Given** the agent proposes an action that needs approval, **When** the run reaches the approval step, **Then** it pauses and shows the approver the campaign, the current and proposed values, the justification and the checks it passed.
2. **Given** a pending approval, **When** the approver approves it, **Then** the action is applied to the live campaign state and logged in the change log with the approver's identity, and it can still be rolled back as on the default track.
3. **Given** a pending approval, **When** the approver rejects it, **Then** nothing changes in the live campaign state and the rejection is recorded.
4. **Given** a pending approval, **When** nobody decides within the configured waiting window, **Then** the action expires as not approved (it fails safe) and the expiry is recorded.
5. **Given** an action the policy allows the agent to run on its own, **When** the agent runs, **Then** it is applied without waiting for a person, exactly as on the default track.

---

### User Story 5 - Understand what each tool replaces and what comes next (Priority: P5)

A workshop participant who wants to keep learning opens the stack track's guide. It maps each tool to the hand-written module it replaces, explains how to run the stack, and lists the later phases. Each later phase states the module it will replace and the workshop block it strengthens.

**Why this priority**: This turns the stack into a study path. Without the mapping, the audience sees a pile of tools and loses the thread.

**Independent Test**: Give the guide to someone who hasn't seen the stack and check whether they can (a) start it and (b) name, for each tool, the module it replaces.

**Acceptance Scenarios**:

1. **Given** the stack guide, **When** a reader looks up any Phase 1 tool, **Then** the guide names the default-track module it replaces and the workshop block it belongs to.
2. **Given** the roadmap section, **When** a reader looks up any later-phase tool, **Then** it lists the module it would replace, the block it strengthens, and the incident or scenario it would make more realistic.
3. **Given** the guide, **When** a reader looks for the stack's known gaps, **Then** it says plainly that in Phase 1 the "centavos" incident (values sent in cents) still passes the contracts, and names the later phase that closes this gap.

---

### Edge Cases

- **Default track untouched**: Starting, running or tearing down the stack must not change the default track's data, configuration or test results. Both tracks can live in the same checkout.
- **SLAs relative to "now"**: The scenario's freshness SLAs depend on the time of generation. A run long after generation must use the documented reference time for parity, or report freshness against the real current time, and say which one it used.
- **Concurrent runs**: If a second daily run is triggered while one is still in progress, it must not corrupt the warehouse. It waits or is refused, and the user is told which.
- **Approval pending at re-run**: If a new run starts while an earlier approval is still pending, the earlier approval must not be applied to data it wasn't decided on (it expires or is superseded, and that is recorded).
- **Incident injection**: The existing incidents (`centavos`, random) can be injected into the stack's data. In Phase 1, the centavos incident is expected to pass the contracts. This is a documented gap, not a defect.
- **Prompt-injected briefing**: The briefing that asks to raise YouTube to R$ 35 mil/day must be refused on the stack exactly as on the default track ("text informs, never authorizes").
- **Service restart mid-run**: If a stack service restarts during a run, the run can be retried from the failed step. Steps already completed don't apply budget changes twice.
- **Low-resource machine**: If the host doesn't meet the documented minimum resources, the start command fails with a clear message instead of leaving services half started.

## Requirements *(mandatory)*

### Functional Requirements

**Packaging and isolation**

- **FR-001**: The stack track MUST live in its own top-level folder and start, stop and reset with documented single commands. It MUST NOT be needed by the default track.
- **FR-002**: The stack track MUST keep its own copy of the warehouse and operational state, separate from the default track's.
- **FR-003**: The stack track MUST reuse the default track's data contracts, business configuration (guardrails, autonomy ladder, budget policy, briefings), scenario generator and agent. It MUST use the same source files, not forked copies, so that one change applies to both tracks.

**Orchestration**

- **FR-004**: The stack track MUST provide one scheduled daily workflow, also triggerable by hand, with these stages in order: ingest raw feeds → contract checks with quarantine and circuit breaker → cleaned layer → business layer with source health → agent run → human approval of escalated actions.
- **FR-005**: Each stage MUST be visible in the orchestrator UI with its status, logs and duration. A failure or block in any stage MUST be visibly distinguishable from success.
- **FR-006**: The workflow MUST be idempotent: re-running it on unchanged inputs MUST give the same business-layer results and MUST NOT apply the same budget change twice.
- **FR-007**: The workflow MUST prevent two runs from writing to the warehouse at the same time.

**Data transformations and contracts**

- **FR-008**: The cleaned and business layers MUST be defined as declarative, versioned transformation models. They replace the hand-written pipeline and MUST keep its semantics: conversions are aggregated before the join (no fan-out), and there is one row per campaign per day. Missing data MUST reach the agent as unknown (NULL), not zero: the business layer publishes per-feed source health (FR-013), and metrics read through the semantic layer come back NULL for campaigns whose feed is stale, exactly as on the default track.
- **FR-009**: Contract checks MUST read the existing ODCS contract files without changing their format.
- **FR-010**: Contract checks MUST keep the default track's row-level behavior: failing rows go to quarantine with their reasons, and valid rows continue.
- **FR-011**: Contract checks MUST keep the per-batch circuit breaker: a batch whose quarantine rate is above the contract's limit is blocked as a whole. Batch status (rows, quarantined, rate, passed/blocked, contract version) MUST be recorded as on the default track.
- **FR-012**: A raw table that is missing a contracted column MUST be treated as a schema violation: the cleaned layer keeps its last good state and the run shows the violation.
- **FR-013**: The business layer MUST publish per-feed, per-partition source health (last successful load, age, SLA, fresh/stale) with the same rules as the default track.

**Agent and human approval**

- **FR-014**: The agent stage MUST run the default track's agent and capabilities with their decision logic unchanged. The default brain MUST be the deterministic rules brain; the Claude brain is opt-in.
- **FR-015**: The agent stage MUST read only the business layer and the live campaign state, as on the default track.
- **FR-016**: Actions that the autonomy ladder routes to a human MUST pause the workflow until a person decides in the orchestrator UI. The approver MUST see the campaign, the current and proposed values, the justification and the checks it passed.
- **FR-017**: Approved actions MUST be applied through the same execution path and change log as on the default track, so rollback still works. Rejections and expiries MUST be recorded with who decided and when.
- **FR-018**: A pending approval MUST expire as not approved after a configurable waiting window, with a documented default.
- **FR-019**: The global autonomy override (shadow, supervised, guarded, full) MUST work on the stack track.

**Parity and verification**

- **FR-020**: The stack track MUST provide a parity check that runs both tracks on the same generated scenario and reference time. It compares the business table, the source-health table and the agent's decisions, and lists every difference.
- **FR-021**: The stack track MUST have automated tests for each Phase 1 promise: the stage order, quarantine, the circuit breaker, schema violation, NULL-not-zero, stale-feed refusal, prompt-injection refusal, approve, reject, expiry and idempotency.
- **FR-022**: The existing default-track test suite MUST still pass unchanged after the stack track is added.

**Documentation and roadmap**

- **FR-023**: The stack track MUST include a guide (pt-BR, consistent with the workshop materials) covering prerequisites, minimum host resources, start/stop/reset, how to trigger a run, how to approve, and how to run the parity check.
- **FR-024**: The guide MUST include a replacement map: each Phase 1 tool → the default-track module it replaces → the workshop block it belongs to.
- **FR-025**: The guide MUST include the later-phase roadmap. For each phase it lists the tool, the module it replaces, the block it strengthens and the scenario it makes more realistic:
  - **Phase 2**: lineage capture and catalog (replaces `lineage`); distribution-anomaly observability for transformations (replaces `observability.py`, and catches the centavos incident that passes the contract).
  - **Phase 3**: a trace collector, agent-trace storage and dashboards (replaces `tracing.py` and the JSONL audit log).
  - **Phase 4**: mock upstream APIs that fail realistically, with a declarative ingestion tool (replaces the static scenario load); policy-as-code guardrails (replaces `config/guardrails.yaml` enforcement); a table format with snapshots for rollback (replaces the single warehouse file).
  - **Phase 5 (optional)**: a metadata catalog with glossary, owners and contracts.
- **FR-026**: Any tool proposed for the stack in any phase MUST name the default-track module it replaces. Proposals that can't name one MUST be rejected.

### Key Entities

- **Daily media run**: One execution of the workflow for a business day. It has stages, a status per stage, a reference time and a link to the agent report it produced.
- **Data contract**: The existing ODCS definition of a feed (columns, types, rules, freshness SLA, freshness partition, maximum quarantine rate, version). This is shared with the default track.
- **Batch status**: For each contract and batch: rows, quarantined rows, quarantine rate, passed/blocked, contract version and load time.
- **Quarantined row**: The original payload of a row that failed, its batch, its violation reasons and when it was quarantined.
- **Source health**: For each feed and partition: last successful load, age, SLA and fresh/stale status.
- **Campaign daily fact**: One row per campaign per day with spend, impressions, clicks, orders, gross revenue and discounts.
- **Approval request**: An action the agent proposed, with its parameters, justification, checks passed, autonomy level, status (pending, approved, rejected, expired), the approver and the time it was decided.
- **Change log entry**: A change applied to the live campaign state (old and new values, actor, justification). It is what rollback works from.
- **Parity report**: The result of comparing both tracks: matching items, differing items with both values, and the reference time used.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: On a machine that meets the documented minimum, a first-time user goes from a fresh checkout to a finished daily run in under 15 minutes, following only the guide (image downloads excluded).
- **SC-002**: The parity check reports zero differences between the two tracks for the default morning scenario, the post-backfill scenario and the supervised-autonomy scenario.
- **SC-003**: 100% of the default track's existing tests still pass after the stack track is added.
- **SC-004**: 100% of the Phase 1 promises in FR-021 are covered by automated tests that pass.
- **SC-005**: In the morning scenario, 0 rows from blocked batches and 0 rows that failed the contract reach the agent.
- **SC-006**: An approver can find, review and decide a pending agent action in the orchestrator UI in under 1 minute.
- **SC-007**: A routine re-run on unchanged inputs produces 0 duplicate budget changes.
- **SC-008**: Every Phase 1 tool appears in the replacement map with a named default-track module. Tools without one: 0.
- **SC-009**: In a dry run with at least one person who hasn't seen it before, the instructor can present the stack track as an add-on to the workshop in 20 minutes or less, including a live run and one approval.

## Assumptions

- **Tool choices for Phase 1 come from the user's request** and are recorded here for planning: Airflow 3 with Postgres as its metadata database; dbt-core with the DuckDB adapter for the Bronze/Silver/Gold models; astronomer-cosmos to show dbt models as orchestrator tasks; datacontract-cli for ODCS validation; Airflow's human-in-the-loop operators for approvals; Docker Compose for packaging. The spec states behavior so that a tool can be swapped later, as long as FR-026 is respected.
- **Row-level quarantine is a likely gap.** Contract-validation tools usually check whole datasets, not individual rows. If the chosen validator can't quarantine row by row and apply the per-batch breaker (FR-010/FR-011), the plan must add that behavior. Dataset-level checks would weaken Block 1's lesson.
- **The warehouse stays an embedded, single-writer, single-file database in Phase 1.** FR-007 (no concurrent writes) follows from this. Moving to a table format with snapshots is Phase 4.
- **No credentials or cloud services are needed.** The stack runs fully local. The Claude brain stays opt-in and needs the user's own API key, as on the default track.
- **The orchestrator's local default login is acceptable** for a workshop/study environment, and is documented as unsuitable for anything exposed to a network.
- **Approval waiting window default**: 20 hours, configurable, so an unanswered request expires before the next daily run instead of delaying it. Demos set it shorter.
- **Minimum host resources** are around 4 CPU cores and 8 GB of free RAM for Phase 1. The plan confirms the final figure.
- **Language**: the stack's user-facing guide and messages are in pt-BR to match the workshop. Code identifiers and this spec are in English.
- **Out of scope for Phase 1**: everything listed under Phases 2–5 in FR-025, plus the MCP server and the semantic layer. Those keep running from the default track; the stack track's agent uses the same capabilities in-process.
