# Implementation Plan: Conversion Metrics "não se aplica" for Awareness Campaigns, in the Data

**Branch**: `006-awareness-roas-not-applicable` | **Date**: 2026-11-27 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/006-awareness-roas-not-applicable/spec.md`

## Summary

The awareness rule moves from text into the data. Each conversion-efficiency metric in the semantic model (ROAS, CAC) declares when it doesn't apply (objective = awareness) and why.

The compiler applies the declaration in SQL:
- at campaign grain, an awareness campaign gets NULL plus a status `nao_se_aplica` and the reason;
- in mixed groups, awareness campaigns are filtered out of those two metrics, with a note saying so;
- the status column keeps "não se aplica" distinct from "desconhecido".

The capability and the MCP tool pass the status and reason through. A display helper makes Blocks 1–2 and `agentready ask` print "não se aplica" instead of NULL. The domain-rule text and policy item 2 are extended to name CAC. The rules brain, the guardrails, the decisions and stack parity are unchanged.

## Technical Context

**Language/Version**: Python ≥ 3.11

**Primary Dependencies**: existing only (duckdb, pyyaml, rich, mcp, opentelemetry-sdk). No new dependency.

**Storage**: unchanged. The semantic model YAML gains a `not_applicable` block on `roas` and `cac` and goes to version 1.2.0.

**Testing**: pytest, offline. New `tests/test_semantic_rules.py`; existing tests unchanged.

**Target Platform / Project Type**: the `agentready` CLI and library; the stack track reaches it through shared code.

**Performance Goals**: no measurable change; two extra aggregate columns per affected metric.

**Constraints**:
- Agent decisions are identical before and after.
- Stack parity stays at 0 differences.
- NULL keeps meaning "desconhecido".
- pt-BR for people, English identifiers.

**Scale/Scope**: 1 YAML rule on 2 metrics; 6 edited modules (`semantic.py`, `capabilities.py`, `blocks.py`, `cli.py`, `ui.py`, and `mcp_server.py` docstring only); 1 policy line; about 12 new tests. Once spec 005 is merged, 005's `toolsets.py` description gets the same rewording (T025).

## Constitution Check

*GATE: checked before Phase 0 research and again after Phase 1 design.*

| Principle | Before research | After design |
|---|---|---|
| **I. The agent is the constant** | Pass. Decision rules aren't touched. | Pass. `_rules` checks the objective before ROAS, and `eligible` requires `roas is not None`, so its decisions can't change (research R4). The demo's decisions are diffed in V-4. The change is to the data architecture (semantic layer), which is what a block's lesson should change. |
| **II. Safety in the backend** | Pass. | Pass. Guardrails and preconditions unchanged; the change makes an existing rule hold in the data instead of depending on the model reading it, which is Principle II's spirit. |
| **III. Missing data is unknown** | Pass, if "não se aplica" isn't NULL-only. | Pass. A third state with its own status column; NULL keeps meaning "desconhecido" for people (display helper) and programs (status column); precedence is defined (research R2). |
| **IV. Deterministic and offline** | Pass. | Pass. Pure SQL compilation; demo stays deterministic. |
| **V. One test per promise** | Pass, with plan. | Pass. `test_semantic_rules.py` covers FR-001 to FR-008; no existing test asserts C05 ROAS/CAC. |
| **VI. Every tool replaces a module** | Pass. No tool added. | Pass. |
| **VII. Accurate claims** | Pass. | Pass. The validation doc records the change and why (the Haiku measurement from 005). |
| **Shared sources** | Semantic model, policy and capabilities are shared by every track. | Changed once, at the source; the stack picks them up through the shared code (no copy). |
| **Workshop structure** | Block 2 behaviour changes on screen. | `docs/01-roteiro-do-instrutor.md` updated in the same change. |

## Project Structure

### Documentation (this feature)

```text
specs/006-awareness-roas-not-applicable/
├── plan.md · research.md · data-model.md · quickstart.md
├── contracts/semantic-model.md · contracts/capability-output.md
├── checklists/requirements.md
└── tasks.md            # /speckit-tasks
```

### Source Code (repository root)

```text
semantic/marketing.semantic.yaml   # EDIT: not_applicable on roas, cac; rule text; version 1.2.0
corpus/politica-orcamento.md       # EDIT: item 2 names ROAS and CAC
src/agentready/semantic.py         # EDIT: load/validate not_applicable; FILTER + status/motivo columns; display()
src/agentready/capabilities.py     # EDIT: pass *_status through, add nao_se_aplica map; round only numbers
src/agentready/mcp_server.py       # EDIT (description only): get_campaign_performance mentions nao_se_aplica
src/agentready/blocks.py           # EDIT: Blocks 1 and 2 tables via semantic.display() + one note
src/agentready/cli.py              # EDIT: `ask` via semantic.display()
src/agentready/ui.py               # EDIT: render the "não se aplica" text distinctly from NULL
tests/test_semantic_rules.py       # NEW
docs/01-roteiro-do-instrutor.md    # EDIT: Block 2 note (rules in text vs rules in data)
docs/00-validacao-do-projeto.md    # EDIT: short entry with the Haiku motivation
```

**Structure Decision**: single project, existing `src/agentready` and `tests/`. No change in `stack/`.

## Complexity Tracking

| Change to shared code | Why needed | Simpler alternative rejected because |
|---|---|---|
| Semantic compiler emits status/motivo columns for metrics with a rule | FR-001/FR-003: rule declared once, and a third state distinct from NULL | A Python post-processing step in the capability wouldn't fix totals or `ask`, and would put the rule outside the semantic model (FR-001). |
| Policy item 2 and the domain-rule text change | FR-004a: text and data must agree after option C | Leaving the text naming only ROAS would make the data stricter than the written rule, and a reviewer couldn't trace why CAC disappeared. |
