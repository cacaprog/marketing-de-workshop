# Feature Specification: Stack Track Phase 2 — Lineage and Data Observability

**Feature Branch**: `002-stack-lineage-observability`

**Created**: 2026-11-24

**Status**: Draft

**Input**: User description: "Phase 2" — the next phase of the stack-track roadmap defined in `specs/001-stack-production-track/spec.md` (FR-025) and `stack/README.md` ("Roteiro das próximas fases"): OpenLineage + Marquez replaces the `lineage` command (Blocks 4, 5), with lineage emitted by the pipeline itself up to the agent's decision; Elementary (data observability in dbt) replaces `observability.py` (Block 5), with volume and distribution anomaly detection that **catches the `centavos` incident that passes the contract**.

## Context

Phase 1 (`specs/001-stack-production-track`) put the daily Aurora media run on production tools: orchestrator, transformation framework, contract validation and human approvals. It left two known gaps, both documented in `stack/README.md` → "Lacunas conhecidas":

1. **The `centavos` incident passes the contracts.** After the upstream deploy, order values arrive 100× too large. They are still numeric and ≥ 0, so the batch is approved, the health signal stays green, and average ticket in the cleaned layer jumps from ~R$ 199 to ~R$ 20 thousand. On the default track, Block 5 catches this with the **distribution** pillar of `observability.py`. The stack track has no equivalent yet.
2. **Lineage and the five-pillar report still come from the default track.** The `agentready lineage` command reads a hand-written dictionary of nodes (`observability.LINEAGE`). The `agentready observe` command runs hand-written SQL checks. Neither is produced by the stack's own pipeline.

Phase 2 closes both gaps. It applies the same governing rule as Phase 1: **a tool joins the stack only if it replaces an existing module.**

| Capability | Replaces (default track) | Block |
|---|---|---|
| Lineage emitted by the running pipeline, stored and browsable | `agentready lineage` + `observability.LINEAGE` / `downstream()` / `decisions_since()` | 4, 5 |
| Data observability (freshness, volume, distribution, schema) computed by the transformation layer | `observability.py` (`report()`, `freshness/volume/distribution/schema`, `block_anomalous_batches()`) and `agentready observe` | 5 |

The Block 5 lesson stays the same, and the stack track can now teach it on its own: **a contract catches what is invalid; observability catches what is valid but wrong.**

## Clarifications

### Session 2026-11-24

- Q: Should Phase 2 include upgrading the transformation framework (dbt-core 1.10, past regular support) to a supported version, or defer it? → A: Include it, as the first step before the observability tool is added (Option A).
- Q: Should anomalies be decided by the default track's median-ratio rule or by the observability tool's built-in anomaly statistics? → A: The default track's median-ratio rule, written as custom tests inside the observability tool. Parity compares exact pass/fail per pillar and target (Option A).
- Q: Where do squads read the data-health (five-pillar) results during Block 5 triage on the stack track? → A: In the observability tool's web report, served locally and rebuilt each run, plus a pt-BR five-pillar summary in the orchestrator run's observability step (Option A).
- Q: How does the instructor turn on the distribution breaker on the stack track? → A: The shared `config/guardrails.yaml` setting is the default, and an optional per-run parameter on the daily run can override it. The parity check always uses the shared setting (Option B).
- Q: With exact parity, how should the stack treat a feed with too little history for a baseline? → A: The stack reports a warning ("histórico insuficiente") that never blocks. The parity check treats a stack warning as equal to a default-track pass (Option C).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - The stack catches the `centavos` incident that passes the contract (Priority: P1)

The instructor triggers the daily run with the `centavos` incident injected. Contract checks pass, as they do in Phase 1. The new observability step then flags the redelivered order-value batch as a **distribution anomaly**: its average ticket is far outside the historical band. The run and the observability report show this as a failed check that names the feed, the batch, the column and the size of the deviation. If the post-mortem corrective action is on (promote the distribution check to a circuit breaker), the anomalous batch is quarantined and blocked before the business layer is built, so it never reaches the agent.

**Why this priority**: This is the gap named in the Phase 1 guide and the reason Phase 2 exists. Without it, the stack track can't deliver the core Block 5 lesson.

**Independent Test**: Trigger one run with `centavos`. Confirm that contract checks pass, the distribution check fails for the ga4 conversions feed, and the failure is visible in the orchestrator and the observability report. Turn on the breaker setting and run again. Confirm the batch is quarantined and the agent sees no data from it.

**Acceptance Scenarios**:

1. **Given** the stack running with the default scenario and no incident, **When** a daily run finishes, **Then** every observability check (freshness, volume, distribution, schema) passes. Exception: checks the default track also flags in the same scenario (e.g., the stale Meta feed) fail on both tracks.
2. **Given** a run triggered with the `centavos` incident and the breaker setting off, **When** the run finishes, **Then** contract checks pass, the distribution check fails for the ga4 conversions order value, and the failure states the batch, the observed average ticket, the baseline and the ratio. The agent still runs, as on the default track. That is what makes it an incident.
3. **Given** a run triggered with the `centavos` incident and the breaker setting **on**, **When** the run finishes, **Then** the anomalous batch is in quarantine with a reason that names the distribution anomaly. Its status is blocked, and none of its rows reach the business layer or the agent.
4. **Given** runs with the `renomeacao`, `lote_duplicado` and `feed_parado` incidents, **When** each run finishes, **Then** the observability report flags the same pillar the default track flags for that incident (schema, volume, freshness).

---

### User Story 2 - Parity of the observability verdicts with the default track (Priority: P2)

The instructor runs the parity check, which now also compares the observability verdicts. For each scenario (no incident and each of the four incidents), both tracks agree on which pillar fails for which target. The checks themselves now live in the transformation layer instead of hand-written Python, but the conclusions match.

**Why this priority**: Phase 1's parity check proves the agent is unchanged. Phase 2 has to prove that replacing `observability.py` didn't change what the instructor tells the audience. It comes after P1 because the detection must exist before it can be compared.

**Independent Test**: Run the extended parity check across the default scenario and the four incident scenarios. Confirm it reports zero differences in pass/fail per pillar and target, and zero differences in the Phase 1 items (business table, source health, agent decisions).

**Acceptance Scenarios**:

1. **Given** both tracks on the same generated scenario and reference time, **When** the parity check runs, **Then** it compares the pass/fail verdict per pillar and target from both tracks and lists every difference.
2. **Given** an incident scenario, **When** the parity check runs, **Then** the incident's pillar is failing on both tracks, and the business table and agent decisions still match as in Phase 1.
3. **Given** a deliberate change to one track's anomaly band, **When** the parity check runs, **Then** it reports the difference rather than passing silently.

---

### User Story 3 - Trace an incident's blast radius through pipeline-emitted lineage (Priority: P3)

During Block 5 triage, a squad opens a lineage view in the browser. They start from the ga4 feed and follow it through the raw, cleaned and business layers to the agent's run and the budget changes it made. The lineage isn't a hand-drawn map: every run records it as it executes, with the run's time and status on each step. From the agent step, the squad can see which decisions were made after the incident started. Those are the rollback candidates.

**Why this priority**: Lineage turns "something is wrong" into "this is what it touched". That is the second half of Block 5 triage and part of the Block 4 audit story. It ranks below detection (P1) and parity (P2): if detection fails, there is nothing to trace.

**Independent Test**: After one normal run and one `centavos` run, open the lineage view. Confirm the path from the ga4 feed to the agent's decision step exists, was recorded by those runs (with timestamps), and that the decisions made after the incident can be listed from it or next to it.

**Acceptance Scenarios**:

1. **Given** a finished daily run, **When** the user opens the lineage view, **Then** they see every dataset the run read or wrote (raw, quarantine, cleaned, business, source health) and the steps that link them, ending at the agent step and the live campaign state it changes.
2. **Given** several runs, **When** the user selects a dataset or step, **Then** they see the history of the runs that touched it, with status and time.
3. **Given** a `centavos` run, **When** the user starts from `bronze.conversions` (where the ga4 feed lands; per-source feed nodes arrive with Phase 4's live ingestion), **Then** they reach the agent step, and can list the agent decisions executed or queued since the incident's injection time, with trace ids matching the change log.
4. **Given** the stack restarts, **When** the user opens the lineage view, **Then** lineage from earlier runs is still there until the documented reset command is run.

---

### User Story 4 - The guide explains what Phase 2 replaced and updates the gaps (Priority: P4)

A reader of the stack guide sees the two new tools in the replacement map, each with the module it replaces and the block it supports. The "known gaps" section no longer says `centavos` passes undetected. The roadmap shows Phase 2 as done and lists any honest partial replacements. The instructor script tells the instructor how to run Block 5 on the stack track.

**Why this priority**: Required by Principle VI (replacement map) and Principle VII (accurate claims), but it only documents what P1–P3 build.

**Independent Test**: Read the updated guide. Confirm each Phase 2 tool names a replaced module, the gaps list matches the actual behavior, and a person following only the guide can run the Block 5 flow on the stack.

**Acceptance Scenarios**:

1. **Given** the updated guide, **When** a reader looks at the replacement map, **Then** each Phase 2 tool has a named default-track module, a block, and a note on any part it does not replace.
2. **Given** the updated guide, **When** a reader follows the Block 5 section, **Then** they can inject an incident, find the failing pillar, trace the lineage, roll back the decisions and resolve the incident, using only stack-track interfaces (plus the documented shared commands).

---

### User Story 5 - Move the transformation framework to a supported version (Priority: P5; delivered first)

The Phase 1 guide notes that the transformation framework version is past its vendor's regular support and that upgrading is a next-phase item. Since the observability tool runs inside that framework, Phase 2 upgrades it to a supported version. The existing tests and the parity check confirm nothing changed.

**Why this priority**: It's housekeeping. It matters for the stack's credibility as "how you'd run it in production", but it isn't a lesson, so it ranks last in value. **Sequencing**: it is delivered **first**, before the observability tool is added, because that tool constrains which framework versions are possible. Upgrading first, with Phase 1's tests and parity check as the safety net, keeps any behavior change separate from the Phase 2 changes.

**Independent Test**: After the upgrade, run the full stack test suite and the parity check. Both pass with zero differences.

**Acceptance Scenarios**:

1. **Given** the upgraded framework, **When** the Phase 1 tests and the parity check run, **Then** they pass unchanged.
2. **Given** the upgraded framework, **When** a reader checks the guide, **Then** the version gap no longer appears in the known gaps, or the guide says why it couldn't be closed.

---

### Edge Cases

- **Short history**: if a feed has fewer days of history than the anomaly baseline needs (e.g., right after reset or on a new source), the stack's check MUST report a warning ("histórico insuficiente"), not a pass or a failure. It MUST NOT block the batch, even with the breaker on. The default track reports a pass in the same case, and parity treats the two as equal (FR-015).
- **Legitimate shifts**: a real change in average ticket (e.g., a promotion) inside the band MUST NOT be flagged. One outside the band is flagged, and the breaker setting decides whether it blocks. Bands are configurable and documented.
- **Incident resolved**: after `incident resolve`, the next run MUST pass the distribution check again, and the anomalous batch MUST NOT keep polluting the baseline for later runs.
- **Override vs. shared setting**: a per-run breaker override MUST NOT carry over to later runs, including scheduled ones. Each run without the parameter falls back to the shared setting.
- **Breaker and contract both fire**: when a batch is blocked by the contract (e.g., `renomeacao`), the observability step MUST NOT quarantine the same batch twice or overwrite the contract's reasons.
- **Report build fails**: if the web report can't be rebuilt, the run's verdicts and the orchestrator summary MUST still be produced. The failed rebuild is a visible warning, not a failed run.
- **Lineage backend down**: if the lineage store is unavailable, the daily run MUST still finish and the agent MUST still decide. The missing lineage MUST be visible (a warning on the run), not silent.
- **Re-runs**: re-running the same day MUST NOT create duplicate anomaly records or duplicate lineage runs that look like separate business days. Each orchestrator run is one lineage run.
- **Observability fails to run** (as opposed to finding an anomaly): if the breaker's input fails, Silver and Gold aren't rebuilt (the agent keeps the last good data, as with a schema break). If the verdict step fails, the agent doesn't run. Both are visible failed steps (FR-008).
- **Host resources**: the new services push past Phase 1's documented minimum. The guide MUST state the new minimum, and the stack MUST still start on it.

## Requirements *(mandatory)*

### Functional Requirements

**Data observability (replaces `observability.py`)**

- **FR-001**: The daily run MUST include an observability step after the business layer and source health are built, and before the agent runs. (The freshness pillar reads source health, so it can't run earlier. The distribution breaker in FR-005 acts earlier, inside the contract stage, before the business layer.) It MUST compute the four data pillars the default track computes: freshness per feed/partition, volume per source, distribution of order value per batch, and schema conformance per contract.
- **FR-002**: The distribution check MUST compare each new batch's average order value against the historical median for that source, using the same band as the default track (0.5×–2.0×) unless configured otherwise. The volume check MUST use the same band as the default track (0.5×–1.5× of the 14-day median) unless configured otherwise. These checks MUST be the default track's median-ratio rules, written as custom tests inside the observability tool. The tool's built-in statistical anomaly tests MUST NOT decide any verdict or drive the breaker.
- **FR-003**: Each failed check MUST report the pillar, the target (dataset and, where it applies, source, column or batch), the observed value, the baseline and the deviation (where applicable; not for schema), in pt-BR wording that matches the default track's report.
- **FR-004**: Observability results MUST be stored per run, so a check's history can be viewed over time. They MUST be shown in two places: (a) a web report from the observability tool, served locally at a documented address and rebuilt at the end of every run, with each check's history; (b) a pt-BR five-pillar summary table (pillar, target, ok, detail, in the same shape as `agentready observe`) in the logs of the orchestrator run's observability step, with the step marked as having failures when any check fails.
- **FR-005**: The existing guardrail setting `observability.block_on_distribution_anomaly` MUST control the breaker on the stack track too. When on, batches flagged by the distribution check MUST be moved to quarantine with the reason "anomalia de distribuição: ticket médio fora da banda" and marked blocked before the business layer is built. When off, the check only reports. The setting MUST be read from the shared configuration, not copied. The daily run MUST also accept an optional per-run parameter (default: "use shared setting"; other values: on, off) that overrides it for that run only, without changing the shared file. The effective value and where it came from MUST be shown in the run. The parity check MUST NOT use the override.
- **FR-006**: With the `centavos` incident injected, contract checks MUST still pass (the gap is real and stays visible) and the distribution check MUST fail. This is the Phase 2 acceptance test for the incident.
- **FR-007**: For each of the four incidents, the stack observability report MUST flag the same pillar the default track's report flags.
- **FR-008**: A failure to *compute* (as opposed to finding anomalies) MUST fail safe at the point where it happens: (a) if the distribution breaker's input can't be computed in the contract stage, the cleaned and business layers MUST NOT be rebuilt for that run, whether the breaker is on or off; (b) if the observability verdicts can't be computed after the business layer, the agent MUST NOT run. In both cases the failing step MUST be marked failed.

**Lineage (replaces the `lineage` command and the hand-written lineage map)**

- **FR-009**: Every daily run MUST emit lineage events as it runs: one per step, linking the datasets it read to the datasets it wrote. The events MUST cover ingest, contract checks (including quarantine and batch status), the cleaned layer, observability, the business layer and source health, and the agent step.
- **FR-010**: The agent step MUST appear in lineage with its inputs (the business-layer and source-health datasets it read) and its output (the live campaign state, through the change log and the approval queue). It MUST carry the run's trace id so lineage can be joined to the change log.
- **FR-011**: Lineage MUST be stored in a lineage service that is part of the stack and browsable in a web UI at a documented local address. It MUST keep run history across stack restarts until the documented reset.
- **FR-012**: Users MUST be able to answer "what is downstream of the ga4 feed (`bronze.conversions` in lineage)" and "which agent decisions happened since time T" with stack-track tools. The second question MAY still use a shared command or query when the lineage store can't hold decision-level data, and the guide MUST say so.
- **FR-013**: A lineage-store outage MUST NOT fail the daily run or change the agent's decisions. The run MUST record a visible warning.
- **FR-014**: The hand-written lineage map MUST NOT be copied into the stack. Lineage MUST come from what the pipeline actually ran. Static nodes that no pipeline step produces (e.g., semantic metrics, MCP tools) MAY be left out, and the guide MUST list them as a partial replacement.

**Parity and verification**

- **FR-015**: The parity check MUST also compare the observability verdicts between tracks with an exact match on the verdict per pillar and target (not just "the incident's pillar fails"). A stack "warning" (short history) counts as equal to a default-track pass, and is the only allowed mapping between verdicts. The parity check MUST cover Phase 1's three scenarios plus each of the four incidents. It MUST still compare the Phase 1 items.
- **FR-016**: The stack MUST have automated tests for each Phase 2 promise: `centavos` detected by distribution while the contract passes, breaker on → batch quarantined and blocked, breaker off → report only, per-run override wins for that run only, short history → warning not failure, one pillar per incident, lineage emitted for every step including the agent, run survives a lineage-store outage, no duplicate quarantine when contract and breaker both fire.
- **FR-017**: The default-track test suite and the Phase 1 stack tests MUST still pass unchanged.
- **FR-018**: The default track MUST NOT change. `observability.py` and the `lineage`/`observe` commands stay as they are for the zero-container demo.

**Platform upkeep**

- **FR-019**: The transformation framework MUST be upgraded to a version within its vendor's regular support, if one is compatible with the observability tool and the warehouse adapter. The upgrade MUST be the first Phase 2 change, made and verified (Phase 1 tests and parity check passing, with 0 differences) **before** the observability tool or lineage emission is added. If no compatible supported version exists, the guide MUST say why.

**Documentation**

- **FR-020**: The stack guide (pt-BR) MUST add each Phase 2 tool to the replacement map, with the module it replaces, the block, and any partial-replacement notes.
- **FR-021**: The guide MUST update "Lacunas conhecidas": remove the `centavos` and lineage gaps that are now closed, add any new honest gaps, and update the roadmap to mark Phase 2 as done.
- **FR-022**: The guide MUST include a Block 5 runbook for the stack track: inject → detect (the observability step's summary, then the web report) → trace (lineage) → roll back → resolve, with TTD/TTR as on the default track. It MUST also give the new minimum host resources and the new local addresses.
- **FR-023**: Every tool added in Phase 2 MUST name the default-track module it replaces (Principle VI). Proposals that can't name one MUST be rejected.

### Key Entities

- **Observability check result**: One pillar's verdict for one target in one run: pillar (frescor, volume, distribuição, esquema), target, pass/fail/warning, observed value, baseline, deviation, run id, time.
- **Anomaly band**: Configured lower/upper ratios for volume and distribution, plus the minimum history needed for a baseline. Shared with the default track where it is already defined.
- **Breaker setting (effective)**: For each run, whether the distribution breaker was on, and its source (shared config or per-run override).
- **Distribution-blocked batch**: A batch quarantined by the observability breaker rather than by the contract. It is told apart by its quarantine reason, and its status is blocked.
- **Lineage run event**: A record that a pipeline step started or finished in a given run, with the datasets it read and wrote, its status, time, and (for the agent step) the trace id.
- **Lineage dataset node**: A dataset the pipeline reads or writes (raw, quarantine, cleaned, business, source health, batch status, change log, approval queue, live campaign state), with the history of runs that touched it.
- **Incident**: The existing Block 5 incident record (kind, injected/detected/resolved times, batch). Detection time is what TTD is measured against.
- **Parity report** (extended): Adds per-pillar/target verdicts to the Phase 1 comparison.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: In 100% of `centavos` runs, the stack flags the anomalous batch through the distribution check while contract checks pass. Today it flags 0%.
- **SC-002**: With the breaker setting on, 0 rows from the `centavos` batch reach the business layer or the agent.
- **SC-003**: The extended parity check reports 0 differences across 7 scenarios (Phase 1's `manha`, `pos_backfill` and `supervisionado`, plus one per incident: `centavos`, `renomeacao`, `lote_duplicado`, `feed_parado`) for business table, source health, agent decisions and observability verdicts.
- **SC-004**: 100% of the Phase 2 promises in FR-016 are covered by automated tests that pass. 100% of the default-track and Phase 1 tests still pass.
- **SC-005**: Every step of a daily run, including the agent step, appears in the lineage view after the run, and a user can go from the ga4 feed to the agent decisions in under 2 minutes.
- **SC-006**: During a Block 5 dry run on the stack, a squad that hasn't seen the incident identifies the failing pillar and the affected decisions (time to detect) in under 10 minutes, using only the stack-track interfaces and the guide.
- **SC-007**: A daily run with Phase 2 still finishes in 5 minutes or less (up to the approval pause), and a first-time user still goes from fresh checkout to a finished run in under 15 minutes on the documented minimum host (image downloads excluded).
- **SC-008**: Every Phase 2 tool appears in the replacement map with a named default-track module. Tools without one: 0.

## Assumptions

- **Tool choices come from the Phase 1 roadmap** (`stack/README.md`, spec 001 FR-025) and are recorded here for planning: **OpenLineage** events, emitted through the orchestrator's OpenLineage provider and the transformation framework's integration, stored and browsed in **Marquez**; **Elementary** as the data-observability package inside the transformation framework. The spec states behavior so either can be swapped, as long as FR-023 holds.
- **Anomaly logic is custom tests, not the tool's statistics.** Generic anomaly detectors use their own statistics (e.g., z-scores over training windows), which don't reproduce the default track's median-ratio bands. Per the clarification, the bands are written as custom tests inside the observability package (FR-002). The tool replaces `observability.py`'s execution, storage, history and reporting, not its decision rule. The guide records this as an honest partial replacement, like Phase 1's row-level quarantine.
- **The breaker setting stays where it is.** `config/guardrails.yaml` → `observability.block_on_distribution_anomaly` is the shared default for both tracks. It is off, so Block 5 shows the incident before the post-mortem's corrective action. The stack's per-run override (FR-005) exists so the "after" can be demoed without editing shared files.
- **Decision-level lineage may stay shared.** Lineage tools model datasets and jobs, not individual budget changes. The list of decisions since time T may keep coming from the change log and approval queue, joined by trace id (FR-012). The guide says so.
- **Static lineage nodes that no pipeline step emits** (semantic metrics, MCP tools, the freshness guard) are out of scope for Phase 2 and are listed as a partial replacement. The semantic layer and MCP server still come from the default track (as in Phase 1).
- **Minimum host resources** rise because of the lineage service and its database. The working estimate is ~4 CPU cores and ~10 GB of free RAM. The plan confirms the figure.
- **Local only, no credentials**: as in Phase 1, every new service runs locally with default local logins, documented as unsuitable for network exposure.
- **Language**: user-facing guide text, check messages and run warnings are in pt-BR. Code identifiers and this spec are in English.
- **Out of scope for Phase 2**: Phases 3–5 of the roadmap (trace collector and dashboards replacing `tracing.py`; mock APIs with declarative ingestion; policy-as-code guardrails; snapshot table format; metadata catalog). Agent decision logic is unchanged (Principle I).
