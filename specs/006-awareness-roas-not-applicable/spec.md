# Feature Specification: Conversion Metrics "não se aplica" for Awareness Campaigns, in the Data

**Feature Branch**: `006-awareness-roas-not-applicable`

**Created**: 2026-11-27

**Status**: Implemented (2026-11-27; T024 and the Haiku re-run wait for 005 + 006 on main)

**Input**: User description: "006-awareness-roas-not-applicable: The awareness rule ("campanhas de awareness são avaliadas por alcance, NUNCA por ROAS") lives only in text today (semantic/marketing.semantic.yaml domain_model.rules and corpus/politica-orcamento.md), while the semantic layer and the get_campaign_performance capability still return a numeric ROAS for awareness campaigns (C05). In the 005 comparison, Claude Haiku 5.5 with the context layer answered "ROAS 0,60" for C05 because the official tool handed it a number and it never read the policy; Opus read the policy and answered "não se aplica". Fix: make the rule live in the data. The official ROAS of an awareness campaign must come back as "não se aplica" with the reason, never a number, from the semantic layer and from every capability/tool/MCP resource that exposes official metrics. It must be distinguishable from NULL, which already means "desconhecido" (stale/missing data, Principle III). The rule should be declared once, in the semantic model, next to the metric (not hard-coded per consumer). Block 2's "oficial vs SQL adivinhado" table shows "não se aplica" for C05. The rules brain's decisions, the default demo's decisions, the guardrails and stack parity must be unchanged (rules brain already skips awareness by objective). Teaching point for the workshop: rules that only exist in text a model may ignore; rules in the data it cannot. Scope: ROAS only (the documented rule); whether CAC also stops applying to awareness is a question to raise, not assume. Materials pt-BR, code English. Depends on nothing from 005 except that the 005 question roas-c05 is the measurement that motivated it and should be re-run after."

## Context

The domain model has three business rules. Two of them already live in the data:
- **"receita é líquida":** the metric is defined net of discounts.
- **"dado atrasado não é zero":** metrics from a stale feed come back NULL with `data_status = stale`.

The third, **"awareness não usa ROAS"**, lives only in text: a rule entry in the semantic model and item 2 of the budget policy. Every official channel still returns a number for the ROAS of C05, the TikTok awareness campaign, about 0,59. That includes the semantic layer, the `get_campaign_performance` capability and the MCP tool.

The 005 comparison showed the cost (research R20 of spec 005):
- **Claude Haiku 5.5, with the context layer**, answered "ROAS 0,60" for C05. The official tool handed it a number, and it never opened the policy.
- **Claude Opus 5.5** read the policy and answered "não se aplica".

The same context layer gave a right answer to one model and a wrong one to the other. The rule depended on the model choosing to read a text.

This feature moves the rule into the data, so every consumer gets it without reading anything. Following how the business acts on these numbers, the rule covers every **conversion-efficiency metric**: a metric that judges a campaign by what its spend converts into. Today that's ROAS and CAC. An awareness campaign is bought for reach and frequency, so a cheap or expensive cost per order says nothing about whether it worked, and acting on it would cut the wrong campaign (clarification 2026-11-27, option C). That gives the workshop a sharper Block 2 point: **a rule that exists only in text, a model may ignore; a rule in the data, it cannot.**

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Official metrics say "não se aplica" for awareness conversion metrics (Priority: P1)

Anyone, or any agent, asking for official metrics gets, for an awareness campaign's ROAS and CAC, an explicit "não se aplica" with the reason ("campanhas de awareness são avaliadas por alcance e frequência"), instead of a number. This holds everywhere official metrics are served: the semantic layer, the capability and the MCP tool. The answer is clearly different from "desconhecido".

**Why this priority**: this is the fix itself; without it, the rule still depends on the reader.

**Independent Test**: request ROAS and CAC by campaign over 14 days from the semantic layer, from the capability and from the MCP tool; check that C05 carries "não se aplica" with the reason and no number for both. Check that C03 and C04 (stale feed) still carry "desconhecido", and that the conversion campaigns' ROAS and CAC are unchanged.

**Acceptance Scenarios**:

1. **Given** the morning scenario, **When** official ROAS and CAC are requested by campaign, **Then** C05 shows "não se aplica" with the reason for both. C01, C02 and C06 show the same numbers as before. C03 and C04 show "desconhecido" (stale), as before.
2. **Given** a request for several metrics at once (spend, net revenue, ROAS, orders, CAC), **When** it returns, **Then** only C05's ROAS and CAC change; its spend, net revenue, orders and CTR are still reported as numbers.
3. **Given** a request grouped by channel or objective, **When** the group contains only awareness campaigns, **Then** its ROAS and CAC are "não se aplica". **When** the group mixes awareness and conversion campaigns, **Then** the awareness campaigns are left out of that group's ROAS and CAC and the result says so.
4. **Given** the MCP tool `get_campaign_performance`, **When** a client calls it, **Then** the C05 row carries the "não se aplica" marker and reason in a form a model can read, with no numeric ROAS or CAC.

---

### User Story 2 - Block 2 shows the rule in the data (Priority: P2)

In Block 2, the instructor's "oficial vs SQL adivinhado" table shows "não se aplica" in the official column for C05, while the three guessed SQL columns still show numbers. The instructor can point at the difference: the guesses don't know the rule, the official layer does.

**Why this priority**: it's how the audience sees the fix; the data change alone is invisible on stage.

**Independent Test**: run `agentready demo 2` and read the table; run `agentready ask "ROAS por campanha"` and read the result.

**Acceptance Scenarios**:

1. **Given** `agentready demo 2`, **When** the official-vs-guessed table prints, **Then** C05's official cell reads "não se aplica" and the other official cells are unchanged.
2. **Given** `agentready ask "qual o ROAS do TikTok?"`, **When** it runs, **Then** the result shows "não se aplica" for C05 with the reason; the same for `agentready ask "CAC por campanha"`.
3. **Given** the instructor script, **When** the presenter reaches the Block 2 table, **Then** the script says what to point at, including the teaching point about rules in text versus rules in data.

---

### User Story 3 - The behaviour that must not change, doesn't (Priority: P1)

The rules brain, the naive agent, the guardrails, the autonomy ladder and every agent decision in the default demo stay exactly as they are. The stack track and its parity check stay at zero differences.

**Why this priority**: Principle I. The fix changes what the data says, not what the deterministic agent decides. The rules brain already skips awareness campaigns by objective before it looks at ROAS.

**Independent Test**: run the full test suite, the default demo and the stack parity check before and after; compare the decisions.

**Acceptance Scenarios**:

1. **Given** the default demo, **When** it runs, **Then** every agent decision and every action in Blocks 0–5 is the same as before. Only official ROAS and CAC values for C05 change on screen.
2. **Given** the stack track, **When** parity runs for every scenario, **Then** it reports 0 differences. That includes agent decisions and Gold, and both tracks show the same official ROAS and CAC output for C05.

### Edge Cases

- **An awareness campaign whose feed is also stale:** "não se aplica" wins. The question doesn't apply whatever the data's freshness, and the status still reports the staleness for the other metrics.
- **A campaign that changes objective:** the rule follows the campaign's current objective in the official dimension.
- **A participant adds a new metric** (e.g., `ticket_medio` in the Block 2 exercise): a per-order value is not a conversion-efficiency metric and stays a number; a new metric that judges a campaign by what its spend converts into must declare the same rule. The guide for the exercise says how.
- **Totals across all campaigns:** a portfolio ROAS or CAC must not silently include awareness spend and revenue. Either awareness campaigns are left out (and the result says so), or the total says it mixes objectives. The plan picks one and states it.
- **Consumers expecting a number** (sorting, "highest ROAS", the floor comparison): they must handle "não se aplica" without crashing and without treating it as 0 or as below the floor.
- **NULL still means "desconhecido":** nothing in this change may turn a stale metric into "não se aplica", or the reverse.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The semantic model MUST declare, next to each conversion-efficiency metric (today ROAS and CAC), when the metric does not apply (campaign objective = awareness) and the reason, in pt-BR. This MUST be the single place the rule is defined for metrics; every consumer derives it from there.
- **FR-002**: Every official metric result MUST report an awareness campaign's ROAS and CAC as "não se aplica" with the reason, never as a number. This covers the semantic layer, the `get_campaign_performance` capability, the MCP tool and the deterministic `agentready ask`.
- **FR-003**: "Não se aplica" MUST be distinguishable from "desconhecido" in every result, for people and for programs. NULL keeps meaning missing or stale data only (Principle III).
- **FR-004**: The rule covers every conversion-efficiency metric: today ROAS and CAC. Spend, net revenue, orders and CTR of awareness campaigns, and every metric of conversion campaigns, MUST be returned exactly as today. *(Clarified 2026-11-27: option C.)*
- **FR-004a**: The written rule MUST say the same as the data, in the same change. The semantic model's domain rule `awareness_nao_usa_roas` (keep its id: spec 005's question set refers to it) MUST be reworded to cover conversion-efficiency metrics (ROAS and CAC). Policy item 2 MUST be extended to match. The policy is versioned configuration, and this feature's PR is the approval its item 7 requires.
- **FR-005**: Grouped results (by channel, by objective, totals) MUST NOT mix awareness campaigns into a ROAS or CAC figure without saying so (see Edge Cases).
- **FR-006**: Block 2's official-vs-guessed table MUST show "não se aplica" for C05's official ROAS; the guessed columns are unchanged.
- **FR-007**: The agent's decision rules, the naive agent, the guardrails, the autonomy ladder and the policy MUST be unchanged. Every agent decision in the default demo MUST be the same as before (Principle I).
- **FR-008**: The stack track MUST show the same official output and keep parity at 0 differences in every scenario. The stack reaches the semantic layer through the shared code, so no stack-only change is expected.
- **FR-009**: Every promise above MUST have an automated test that runs offline (Principle V). The existing tests stay unchanged unless one asserts a numeric ROAS or CAC for C05, which this change makes intentionally wrong; any such test is updated in the same change, with the reason recorded.
- **FR-010**: The instructor script's Block 2 section MUST explain the change and its teaching point. The validation document MUST record it, and the domain-rule text in the semantic model stays as the human-readable statement of the same rule.
- **FR-011a**: Every tool description that tells a model how to read official metrics MUST distinguish NULL with status `desconhecido` from NULL with status `nao_se_aplica`; none may say that NULL always means unknown. This covers the MCP tool now and, once spec 005 is merged, 005's "com contexto" tool.
- **FR-011**: If spec 005 (model comparison) is merged, its business question "Qual o ROAS da campanha TikTok - Awareness (C05)?" MUST be re-run with at least one small model (e.g., Claude Haiku 5.5) after this change, and the result recorded. This is the measurement that motivated the change.

### Key Entities

- **Conversion-efficiency metric**: a metric that judges a campaign by what its spend converts into (ROAS = net revenue ÷ spend; CAC = spend ÷ orders). These are the metrics the awareness rule covers.
- **Metric applicability rule**: belongs to a metric in the semantic model. It says under which dimension value the metric does not apply (objective = awareness) and why (pt-BR text).
- **Metric result cell**: in every official result, a metric value is one of three things: a number, "desconhecido" (missing or stale; today's NULL), or "não se aplica" with its reason.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: In every official channel (semantic layer, capability, MCP tool, `ask`), 100% of awareness-campaign ROAS and CAC values read "não se aplica" with the reason, and 0 are numbers.
- **SC-002**: The ROAS and CAC of every conversion campaign, and every other metric of every campaign, are identical before and after, to the cent.
- **SC-003**: Every agent decision in the default demo is identical before and after, and the stack parity check reports 0 differences in all 7 scenarios.
- **SC-004**: In Block 2's table, C05's official cell shows "não se aplica" in a style distinct from NULL, and the reason is on screen in the same view, while the three guessed cells show numbers. (Whether an audience grasps it unaided is not measured.)
- **SC-005**: After the change, re-running the C05 question from spec 005 with Claude Haiku 5.5 with context gives "não se aplica" (it gave "ROAS 0,60" before). This is a single illustrative run, recorded with date and model.

## Clarifications

### Session 2026-11-27

- Q: Does the rule cover only ROAS, ROAS and CAC, or every conversion metric? → A: Option C, every conversion-efficiency metric (today ROAS and CAC), following how the business acts on them; the written rule and the policy are extended to match (FR-004, FR-004a).

## Assumptions

- The rule is keyed on the campaign's `objective` field in the official campaign dimension, the same field the rules brain already uses.
- Only one objective is covered (awareness) for two metrics (ROAS, CAC). The way it's declared should allow another metric or objective later, but no other objective is added now.
- The policy document and the semantic model's domain-rule text are extended to name CAC (FR-004a); they remain the human-readable explanation of a rule the data now enforces.
- Results for conversion campaigns keep their current shape, so programs that read only conversion campaigns are unaffected.
- The change ships independently of spec 005; its effect on models is measured with 005's question set once both are on `main`.
