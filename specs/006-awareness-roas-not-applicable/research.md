# Research: Conversion Metrics "não se aplica" for Awareness Campaigns

**Feature**: 006-awareness-roas-not-applicable · **Date**: 2026-11-27

## R1. Where the rule is declared

- **Decision**: a `not_applicable` block on each conversion-efficiency metric in `semantic/marketing.semantic.yaml`:
  ```yaml
  roas:
    ...
    not_applicable:
      when: {objective: [awareness]}
      reason: "campanhas de awareness são avaliadas por alcance e frequência, não por eficiência de conversão"
      rule: awareness_nao_usa_roas
  ```
  The same block goes on `cac`. The `rule` key points to the human-readable domain rule, which keeps its id. The semantic model version goes from 1.1.0 to 1.2.0, and traces already record it (`semantic.model_version`).
- **Rationale**: FR-001 says to declare it once, next to the metric, in the file the compiler already reads. Keys are in English like the rest of the model (`label`, `type`, `synonyms`); the reason is in pt-BR because people read it.
- **Alternatives considered**:
  - one global rule mapping objective to blocked metrics (further from the metric, and easy to miss when a metric is added);
  - hard-coding in `capabilities.py` (FR-001 forbids it);
  - a separate YAML file (a second source of truth).

## R2. How "não se aplica" is represented (FR-003)

- **Decision**: three states per affected metric, carried by two columns:
  - the metric column (e.g. `roas`) holds a number, or NULL;
  - a status column `<metric>_status` holds `ok`, `desconhecido` or `nao_se_aplica`.

  When the status is `nao_se_aplica`, a `<metric>_motivo` column carries the reason. Only metrics that declare `not_applicable` get these columns, so every other query keeps its current shape.
- **Rationale**: a string such as "não se aplica" inside a numeric column would break every program that sorts, compares or formats the value (`f"{roas:.2f}"`, `max(..., key=roas)`). A status column keeps the column numeric, and it makes NULL unambiguous for programs. NULL still means "no number"; the status says why. That's FR-003 for programs.
- **Precedence**: `nao_se_aplica` before `desconhecido`. An awareness campaign on a stale feed still reports ROAS/CAC as "não se aplica", because the question doesn't apply whatever the freshness; `data_status` still reports the staleness.
- **Alternatives considered**: a sentinel number (-1 would be read as a real value); dropping the field (silently different shapes per campaign, and a model would just ask again).

## R3. How the compiler applies it

- **Decision**: for a metric with `not_applicable`, every measure summed inside that metric gets `FILTER (WHERE NOT (<condition>))`, with the condition built from `when` (`t.objective IN ('awareness')`). The result follows from the filter:
  - **campaign grain**: an awareness campaign has nothing left to sum, so the value is NULL and the status is `nao_se_aplica`;
  - **mixed groups** (by channel, by objective, totals): the awareness rows are left out of the ROAS/CAC numerator and denominator, the status stays `ok`, and `<metric>_motivo` says "exclui N campanha(s) de awareness";
  - **groups made only of awareness campaigns**: `nao_se_aplica`.

  Status SQL: `CASE WHEN COUNT(*) FILTER (WHERE NOT cond) = 0 THEN 'nao_se_aplica' WHEN _stale AND <metric depends on conversions> THEN 'desconhecido' ELSE 'ok' END`.
- **Rationale**: one mechanism covers the campaign grain and FR-005 (mixed groups) alike. The SQL stays deterministic, so the "same SQL for different phrasings" property and its test still hold.
- **Alternatives considered**: post-processing rows in Python (wouldn't fix totals, and the SQL shown in Block 2 would no longer be the whole truth); a CASE on the final value only (wouldn't exclude awareness from mixed groups).
- **To verify in implementation**: `FILTER` inside the derived `net_revenue` expression (`gross_revenue - discounts`) when nested in a ratio. The plan compiles each measure call with the inherited filter, so both measures get it.

## R4. Every consumer, and what changes for it

| Consumer | Today | After |
|---|---|---|
| `semantic.query` / `compile_sql` | number for C05 ROAS/CAC | NULL + `roas_status`/`cac_status` = `nao_se_aplica` + `*_motivo` |
| `capabilities.get_campaign_performance` (and the MCP tool, which returns it) | rounded numbers | passes the new columns through, plus `nao_se_aplica: {"roas": motivo, "cac": motivo}` on the row so a model reads it in one place |
| Rules brain (`ReadyAgent._rules`) | skips awareness by `objective` before reading ROAS | unchanged: the objective check comes first, and the `eligible` filter already requires `roas is not None` |
| Block 1 table "Gold servida ao agente" | C05 roas = 0,59 | "não se aplica" (display helper, R5) |
| Block 2 "oficial vs palpites" | official C05 = 0,59 | "não se aplica"; the guesses are unchanged |
| `agentready ask` | number | "não se aplica" + reason (display helper) |
| Observability lineage labels (`métrica roas`) | text only | unchanged |
| Stack track | same shared code | same output; parity compares decisions, Gold, health and trace spans, and both tracks run the same compiler |
| Spec 005 (`perguntas`, `compare`), if merged | `roas-c05` rule type `nao_se_aplica`; `abaixo-do-piso` filters by objective | unchanged; re-run `roas-c05` with Haiku (FR-011) |

## R5. Showing it to people

- **Decision**: `semantic.display(rows)` returns copies of result rows in which each affected metric with status `nao_se_aplica` is replaced by the pt-BR text "não se aplica". The tables in Blocks 1 and 2 and `agentready ask` use it, and `ui.table` renders that text in its own colour, distinct from the magenta NULL. Below the Block 2 table, a note gives the reason once.
- **Rationale**: FR-003 for people. On stage, "NULL" next to C05 would read as "dado atrasado", which is exactly the confusion to avoid.

## R6. Text and policy (FR-004a)

- **Decision**:
  - The domain rule `awareness_nao_usa_roas` keeps its id and becomes: "Campanhas com objective = awareness são avaliadas por alcance e frequência, NUNCA por métricas de eficiência de conversão (ROAS, CAC)."
  - Policy item 2 becomes: "Campanhas de **awareness** são avaliadas por alcance e frequência, nunca por métricas de eficiência de conversão (ROAS, CAC). O agente não deve otimizá-las."
- **Rationale**: the text and the data must say the same thing, and spec 005's question set refers to the rule id. The policy's item 7 requires an approved PR for policy changes, and this feature's PR is it.
- **Effect to check**: the policy text is read by `read_policy` (no test compares it) and by the OPA policy in the stack track. The OPA policy reads limits from `guardrails.yaml`, not from this markdown, so no change is needed there.

## R7. Tests

- **Decision**: a new `tests/test_semantic_rules.py`:
  - **Campaign grain:** ROAS/CAC are `nao_se_aplica` with the reason for C05; `desconhecido` for C03/C04; C01, C02 and C06 match the previous values to the cent.
  - **Other metrics:** C05's spend, net revenue and orders are still numbers.
  - **Grouped results:** by objective, `awareness` is `nao_se_aplica`; by channel, `tiktok` (only C05) is `nao_se_aplica` while the other channels stay `ok` (no channel mixes objectives in the scenario, so the mixed case is the total); the total says it excludes 1 campaign.
  - **Stale awareness campaign:** an awareness campaign on a stale feed is still `nao_se_aplica`.
  - **The capability and the MCP tool** return the marker and the reason.
  - **Display:** the helper shows "não se aplica", never NULL.
  - **Unchanged behaviour:** the rules brain's decisions match the known actions (C06 cut queued, C01 +10%), and the default demo's decisions are unchanged.

  `tests/test_workshop.py` doesn't assert C05's ROAS or CAC, so it stays unchanged (FR-009).

## R8. Implementation notes (2026-11-27)

- **As planned**: `FILTER (WHERE NOT (t.objective IN ('awareness')))` is inherited by every measure inside ROAS and CAC, including the measures of the derived `net_revenue` nested in ROAS. C01/C02/C06 ROAS and CAC match the pre-change values to the cent (7,44 · 2,78 · 0,83; 25,35 · 62,70 · 217,55), and the "same SQL for two phrasings" check still says SIM.
- **Demo**: every ⚡ action and 🛑 refusal line in `demo all` is identical to the baseline (12 of 12). What changed on screen: C05's ROAS cells (Blocks 1 and 2) read "não se aplica" in blue; a new note under Block 2's table; the compiled SQL that Block 2 prints is longer (FILTER clauses and status columns); the trace shows `semantic.model_version=1.2.0`.
- **Validation numbering**: on `main` the new validation entry is item 4 (frescor becomes 5); spec 005 also inserts an item 4, so whichever merges second renumbers.
- **Pending**: T024 (reword 005's tool description) and the Haiku re-run wait until 005 and 006 are both on `main`.
- **Stack (2026-11-27)**: make test 175 + 18 passed; parity 0 differences in all 7 scenarios (semantic model 1.2.0 in both tracks).
- **Haiku re-run, quickstart V-6 (2026-11-27, `claude-haiku-5-5`, `--ids roas-c05`, recording `data/compare/perguntas-20261127-163946.json`)**: com contexto → **certa** (`nao_se_aplica`), its explanation quoting the reason from the data and noting C05's data is fresh; sem contexto → inventou número (ROAS 0,68 from raw Bronze). Before 006 the same model with context answered "ROAS 0,60" (R20 of spec 005). SC-005 met; single illustrative run.
