# Dados Prontos para IA Agêntica (agentready) Constitution

## Core Principles

### I. The Agent Is the Constant

The workshop's thesis is that the agent's decision logic stays the same while the data
architecture around it changes. Therefore:

- Code that delivers a block's lesson (contracts, semantics, guardrails, tracing, observability)
  MUST change the data architecture, not the agent's decision rules (`ReadyAgent._rules`,
  `capabilities.py` preconditions).
- `NaiveAgent` and `ReadyAgent` MUST share the same decision policy. They differ only in what data
  and capabilities they can reach.
- Every way of running the scenario (the default track, the stack track and any later one) MUST
  run the same agent source in-process or through MCP, never a fork. Any difference in decisions
  between tracks is a defect.

**Rationale:** if the agent changes, the audience can't tell whether the architecture or the agent
fixed the problem, and the workshop's argument falls apart.

### II. Safety Lives in the Backend, Not the Model

- Text informs and never authorizes. Content from briefings, prompts or any LLM output MUST NOT be
  able to bypass a precondition, a guardrail or the autonomy ladder.
- Every write capability MUST re-check its preconditions against the live state when it runs,
  including when an approved request is executed after a delay.
- Every agent-reachable action MUST declare a reversibility class (R0–R3). R3 actions MUST NOT be
  exposed to the agent.
- Actions above the autonomy level MUST be queued for a human. A request that nobody decides on
  MUST fail safe (not executed).
- Every executed change MUST be logged with its actor and justification, and MUST be reversible
  through rollback when it is R1.

**Rationale:** current models often resist obvious injection, but safety can't depend on that.

### III. Missing Data Is Unknown, Never Zero

- Absent, late or blocked data MUST show up as NULL/unknown in the Gold and semantic layers,
  never as 0.
- Freshness MUST be measured per feed/partition, based on the last successful load, against the
  SLA in the data contract.
- The agent MUST refuse to act on campaigns whose source data is stale.
- Rows that fail a contract MUST be quarantined with their reasons. A batch above its contract's
  quarantine limit MUST be blocked as a whole. Neither may reach the agent.

**Rationale:** the Block 0 disaster (pausing the best campaigns) is caused by "missing" becoming
"zero". Every track MUST make that impossible.

### IV. Deterministic and Offline by Default

- The default track MUST run with no containers, no cloud services, no network and no API key, and
  `agentready setup` MUST reset it in seconds.
- Demos MUST be deterministic: a fixed seed, the rules brain by default, and the Claude brain only
  when requested (`--brain claude`).
- Heavier, production-shaped tracks (e.g., `stack/`) MUST be optional, MUST live in their own
  folder, MUST keep their own state, and MUST NOT be required by, or change, the default track.

**Rationale:** a live workshop can't depend on installs, networks or model variance.

### V. One Automated Test per Promise

- Every behavior a block promises the audience MUST have an automated test that fails if the
  promise breaks.
- New features MUST add tests for their promises and MUST leave the existing suite passing without
  changing it, except to fix a bug in the test itself.
- When a track reproduces another track's behavior, an automated parity check MUST compare the
  Gold tables, source health and agent decisions, and MUST report every difference.

**Rationale:** what is said on stage must be true every time the demo runs.

### VI. Every Tool Replaces a Module

- A tool or framework MAY be added only if it replaces a named existing module or file and
  delivers the same behavior. The replacement MUST be recorded in the track's replacement map.
- Proposals that can't name the module they replace MUST be rejected.
- Prefer one tool per responsibility. Hand-written code is preferred over a dependency when the
  dependency would hide the concept the block teaches.

**Rationale:** adding tools without replacing anything breaks the story told across the blocks
and turns a teaching project into a list of tools.

### VII. Accurate Claims

- Statistics, studies and regulations cited in workshop materials MUST carry their source and
  scope. Vendor studies MUST be labeled as such. Regulatory obligations MUST name who they apply
  to. Claims that can change by event date (e.g., application dates) MUST be flagged.
- Known limitations and gaps (e.g., an incident that passes the contracts) MUST be documented, not
  hidden.
- Corrections are kept in `docs/00-validacao-do-projeto.md`.

**Rationale:** the audience will repeat what they hear, so overstated claims hurt the instructor's
credibility.

## Tracks and Materials

- **Language:** user-facing materials (docs, CLI messages, guides, templates) MUST be in pt-BR.
  Code identifiers, specs and plans are in English.
- **Shared sources:** data contracts (`contracts/*.odcs.yaml`), business configuration
  (`config/`), budget policy and briefings (`corpus/`), the scenario generator and the agent are
  the single source of truth for every track. A track MUST reference them, not copy them.
- **Contract format:** data contracts stay in ODCS. A change to the format MUST be an amendment
  to this constitution.
- **Workshop structure:** Blocks 0–5 and their commands (`agentready demo 0..5`) are a public
  interface for instructors. Renaming or reordering blocks requires updating
  `docs/01-roteiro-do-instrutor.md` in the same change.

## Development Workflow and Quality Gates

- Features follow Spec Kit: specify → (clarify) → plan → tasks → implement. Every plan MUST pass
  the Constitution Check against Principles I–VII before it is designed and again after.
- Merge gates: `uv run pytest -q` passes; parity checks pass for any track that claims parity;
  every new tool appears in the replacement map (Principle VI); new user-facing text is in pt-BR.
- Any added complexity (a new service, dependency or track) MUST be justified in the plan's
  Complexity Tracking table.
- The Claude model used for the optional brain MUST be the latest available model and MUST be
  configurable, never hard-coded across several files.

## Governance

- This constitution overrides informal conventions in this repository. If it conflicts with a
  spec or plan, the constitution wins until it is amended.
- **Amendments:** propose them through `/speckit-constitution` with a rationale. Every amendment
  updates the Sync Impact Report, the version and the Last Amended date, and checks that the
  existing specs and plans still comply.
- **Versioning (semver):** MAJOR for removing or redefining a principle in a way that breaks
  compatibility; MINOR for adding a principle or section, or materially expanding one; PATCH for
  wording and clarifications.
- **Compliance review:** `/speckit-plan` (Constitution Check) and `/speckit-analyze` MUST flag
  violations. A violation that is accepted MUST be recorded in Complexity Tracking with the
  simpler alternative that was rejected and why.

**Version**: 1.0.0 | **Ratified**: 2026-11-24 | **Last Amended**: 2026-11-24
