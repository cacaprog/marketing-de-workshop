---

description: "Task list for 006 — conversion metrics 'não se aplica' for awareness campaigns"
---

# Tasks: Conversion Metrics "não se aplica" for Awareness Campaigns, in the Data

**Input**: Design documents from `/specs/006-awareness-roas-not-applicable/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/ (semantic-model, capability-output), quickstart.md

**Tests**: REQUIRED. FR-009 and constitution Principle V ask for one offline test per promise. Write each story's tests first and confirm they fail.

**Organization**:
- **US1** (P1): official metrics say "não se aplica".
- **US3** (P1): unchanged behaviour. It's a gate that runs right after US1.
- **US2** (P2): Block 2 and the screens.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel (different files, no dependency on an unfinished task)
- **[Story]**: US1–US3 from spec.md
- All paths are relative to the repo root.

## Global rules for every task

- **Allowed edits:** `semantic/marketing.semantic.yaml`, `corpus/politica-orcamento.md`, `src/agentready/{semantic,capabilities,mcp_server,blocks,cli,ui}.py`, `tests/test_semantic_rules.py` (new), `docs/01-roteiro-do-instrutor.md`, `docs/00-validacao-do-projeto.md`.
- **Must not change:** `agent.py` (the rules brain and the naive agent), `policy.py`, `autonomy.py`, `config/guardrails.yaml`, `generate.py`, `pipeline.py` and anything in `stack/`. If a task seems to need one of them, stop and ask.
- **Existing tests are not edited.** `tests/test_workshop.py` and `tests/test_policy.py` stay as they are, and `uv run pytest -q` must pass after every edit to shared code.
- **NULL keeps meaning "desconhecido".** "Não se aplica" is always carried by a `*_status` column, never by NULL alone.
- **Language:** pt-BR for every user-facing string; English identifiers.

---

## Phase 1: Setup

- [X] T001 Record the baseline on a scratch database (`AGENTREADY_DB`/`AGENTREADY_TRACES` pointing to a temp folder), saved to a scratch folder:
  - the official ROAS, CAC, spend, net revenue and orders per campaign (14 days) from `semantic.query`;
  - the full output of `get_campaign_performance`;
  - `uv run agentready demo all --no-pause`.

  T013 and T021 compare against this baseline.

---

## Phase 2: Foundational (the rule in the semantic model)

- [X] T002 In `semantic/marketing.semantic.yaml`:
  - add the `not_applicable` block to `roas` and to `cac`, exactly as in `contracts/semantic-model.md`: `when: {objective: [awareness]}`; `reason: campanhas de awareness são avaliadas por alcance e frequência, não por eficiência de conversão`; `rule: awareness_nao_usa_roas`;
  - reword the domain rule `awareness_nao_usa_roas` (keep its id) to the text in research R6;
  - set `version: 1.2.0`.
- [X] T003 [P] In `corpus/politica-orcamento.md`, change item 2 to the text in research R6 (ROAS and CAC). No other item changes.
- [X] T004 In `src/agentready/semantic.py`, validate `not_applicable` when the model loads. "The compiler refuses to load a `when` column that isn't in the table, or a `rule` id that doesn't exist", with a pt-BR `SemanticError` naming the metric. Allowed dimension columns are those listed in `semantic_model.dimensions`.

**Checkpoint**: `uv run pytest -q` still passes; the YAML loads; the compiler doesn't use the new block yet.

---

## Phase 3: User Story 1 — Official metrics say "não se aplica" (Priority: P1) 🎯 MVP

**Goal**: every official channel returns "não se aplica" with the reason for awareness ROAS and CAC, distinct from "desconhecido".

**Independent Test**: quickstart V-2 and V-3.

### Tests for User Story 1

- [X] T005 [P] [US1] Create `tests/test_semantic_rules.py` with campaign-grain tests on the seeded scenario, using the `con` fixture:
  - C05 has `roas`/`cac` NULL, `roas_status`/`cac_status` = `nao_se_aplica`, and `*_motivo` = the reason from the YAML;
  - C03 and C04 have `desconhecido`;
  - C01, C02 and C06 have status `ok`, with the same ROAS and CAC as `semantic.query` gave before the change (assert the values from the contract table: 7,44 · 2,78 · 0,83 and 25,35 · 62,70 · 217,55, `pytest.approx` to 0.01);
  - C05's spend, net revenue and orders are still numbers.
- [X] T006 [P] [US1] In `tests/test_semantic_rules.py`, add grouped tests:
  - group by objective → `awareness` row is `nao_se_aplica` for ROAS and CAC; `conversion` row is `ok`;
  - group by channel → `tiktok` is `nao_se_aplica`; other channels `ok`;
  - no grouping (total) → status `ok` and `roas_motivo` = "exclui 1 campanha(s) de awareness";
  - the total ROAS equals a manual ratio of sums over the non-awareness campaigns only;
  - the rule follows the objective in `gold.campaign_daily`: after setting C02's objective to `awareness` in the test's scratch DB, C02 becomes `nao_se_aplica` (edge case "campaign that changes objective").
- [X] T007 [P] [US1] In `tests/test_semantic_rules.py`, add:
  - **stale awareness campaign:** an awareness campaign on a stale feed is still `nao_se_aplica`. Build the case by updating `gold.dim_campaign`/`gold.campaign_daily` so that C03's objective is `awareness` in the test's scratch DB; never touch shared files;
  - **load-time validation:** a model with `when: {canal_inexistente: [x]}` or `rule: nao_existe` is refused with a pt-BR error naming the metric.
- [X] T008 [P] [US1] In `tests/test_semantic_rules.py`, add capability and MCP tests:
  - `capabilities.get_campaign_performance` returns, for C05, `roas_status`/`cac_status` = `nao_se_aplica` and a `nao_se_aplica` map with both reasons; for C03, `desconhecido`; no `nao_se_aplica` key on C01;
  - the MCP tool `get_campaign_performance` (called through `server.call_tool`, as the existing MCP test does) returns the same marker;
  - its description mentions `nao_se_aplica` and does not contain "Métricas NULL = fonte fora do SLA".

### Implementation for User Story 1

- [X] T009 [US1] In `src/agentready/semantic.py`, apply the rule in `compile_sql` per research R3 and `contracts/semantic-model.md`:
  - for each requested metric with `not_applicable`, every measure inside it gets `FILTER (WHERE NOT (cond))`, with `cond` built from `when` as `t.<col> IN (<quoted values>)`;
  - add the inner columns `_<m>_ok` and `_<m>_excl`;
  - in the outer select, add `<m>` (NULL when `_<m>_ok = 0`), `<m>_status` ("`nao_se_aplica` > `desconhecido` > `ok`") and `<m>_motivo`;
  - metrics without a rule compile exactly as before.
- [X] T010 [US1] In `src/agentready/semantic.py`, add `display(rows, metrics=None)`. It returns copies in which each `<m>` with `<m>_status == 'nao_se_aplica'` becomes the text `não se aplica`, and drops the `*_status`/`*_motivo` columns. Add `motivos(rows)`, which returns the distinct reasons so screens can print them once.
- [X] T011 [US1] In `src/agentready/capabilities.py` `get_campaign_performance`:
  - round only numeric values (`isinstance(v, (int, float))`);
  - keep `roas_status`/`cac_status`;
  - add the `nao_se_aplica` map `{metric: motivo}` only on rows where a metric doesn't apply, and drop the `*_motivo` columns from the row (contract `capability-output.md`);
  - record `result.nao_se_aplica` (the campaign ids) on the span.
- [X] T012 [US1] In `src/agentready/mcp_server.py`, **rewrite** (not append to) the sentence "Métricas NULL = fonte fora do SLA (dado desconhecido, não zero)." in the `get_campaign_performance` docstring as: "Métrica NULL com status `desconhecido` = fonte fora do SLA (não é zero); com status `nao_se_aplica` = a métrica não se aplica à campanha (veja o motivo)." The docstring must not keep any sentence saying that NULL always means unknown. No other change to the server.

**Checkpoint**: T005–T008 pass; quickstart V-2 (the raw `semantic.query` part) and V-3 hold.

---

## Phase 4: User Story 3 — Behaviour that must not change, doesn't (Priority: P1)

**Goal**: identical decisions, and stack parity at 0 differences.

**Independent Test**: quickstart V-1, V-4 (decision diff), V-5.

- [X] T013 [US3] In `tests/test_semantic_rules.py`, add a decision test: `ReadyAgent().run(con)` on the seeded scenario produces the same actions as before:
  - `adjust_campaign_budget(C06, 2800.0)` queued;
  - `adjust_campaign_budget(C01, 4400.0)` executed;
  - refusals for C03 and C04;
  - a "fora_do_escopo" thought for C05.

  `NaiveAgent().run(con)` still pauses C03, C04 and C05. Compare with the T001 baseline.
- [X] T014 [US3] Run `uv run pytest -q`: all existing tests pass unchanged, plus the new ones.
- [X] T015 [US3] Run `cd stack && make test && make parity SCENARIO=todos` (no short timeout; `make test` takes about 26 minutes). Expect 0 differences in all 7 scenarios. The semantic model version bump (1.1.0 → 1.2.0) changes the stack's run fingerprint (`ledger.fingerprint` includes `model_version_info()`), so the first stack agent run after the change is recorded as a new run, not a repeat. That's expected and is not a parity problem. If parity reports a difference in trace spans because of the new SQL, both tracks run the same compiler, so investigate before changing anything.

**Checkpoint**: Principle I verified. The change is in the data, not in decisions.

---

## Phase 5: User Story 2 — Block 2 shows the rule in the data (Priority: P2)

**Goal**: people see "não se aplica" (not NULL) and the reason, where the workshop shows official metrics.

**Independent Test**: quickstart V-2 (`ask`) and V-4.

### Tests for User Story 2

- [X] T016 [P] [US2] In `tests/test_semantic_rules.py`, add display tests (with a wide `rich` console, as in other tests):
  - `ui.table(semantic.display(rows))` renders `não se aplica` for C05 and `NULL` for C03;
  - the Block 2 official-vs-guessed table built by `blocks.block2` shows `não se aplica` in C05's official cell while the guessed columns are numbers (capture the console output with `ui.PAUSE = False`).

### Implementation for User Story 2

- [X] T017 [US2] In `src/agentready/ui.py`, render the text `não se aplica` in its own style (e.g. `[blue]não se aplica[/]`), distinct from the magenta `NULL`.
- [X] T018 [US2] In `src/agentready/blocks.py`:
  - **Block 1:** the "Gold servida ao agente" table uses `semantic.display(perf)`.
  - **Block 2:** the official column of the official-vs-guessed table uses the display value; under it, print one `ui.note` with the reason: "C05 é awareness: ROAS e CAC não se aplicam (regra no modelo semântico, não só no texto)." The result table at the end of Block 2 also uses `semantic.display()`.
  - No other text or step changes.
- [X] T019 [US2] In `src/agentready/cli.py` `cmd_ask`, show `semantic.display(rs)` and print `semantic.motivos(rs)` once as a note.
- [X] T020 [P] [US2] In `docs/01-roteiro-do-instrutor.md`, Block 2 "Na demo, aponte": add the C05 cell. The official layer says "não se aplica" while the three guesses show a number; *"regra que só existe em texto, o modelo pode ignorar; regra no dado, não"*. Mention that the 005 comparison showed Claude Haiku answering ROAS 0,60 before this change.
- [X] T021 [US2] Run quickstart V-4: diff `demo all --no-pause` against the T001 baseline (normalising ids, timestamps, the incident id and paths). Every ⚡ action and 🛑 refusal line must be identical; only C05's ROAS/CAC cells and the new note may differ.

---

## Phase 6: Polish

- [X] T022 [P] In `docs/00-validacao-do-projeto.md`, add a short entry: the awareness rule now lives in the data for ROAS and CAC. Give the reason: 005's measurement, where Haiku 5.5 with context answered ROAS 0,60 for C05. Note the policy item 2 change and that this PR is its approval (policy item 7).
- [X] T023 Grep `src/agentready/` for consumers of `roas`/`cac` that format or compare without a None check, and confirm each is safe with C05 = NULL. Known safe: `agent.py` (objective first), `ui._cell`.
- [X] T024 When spec 005 and this feature are both on `main` (whichever merges second does this), rewrite the `get_campaign_performance` description in `src/agentready/toolsets.py` (005's "com contexto" toolset) from "Métrica NULL = dado desconhecido, nunca zero." to the same wording as T012. Add a test in `tests/test_semantic_rules.py` asserting that neither description says NULL always means unknown. Do this **before** the T025 Haiku re-run, or the measurement is invalid.
- [X] T025 Update the `spec.md` status to "Implemented". Record in `research.md` any deviation found during implementation. If spec 005 is on `main` by then (and T024 is done), run quickstart V-6 (Haiku, `roas-c05`) and record the result with date and model; otherwise note it as pending until both are merged (FR-011).

---

## Dependencies & Execution Order

- **Phase 1** (T001) → **Phase 2** (T002–T004; T003 [P] alongside).
- **US1** (T005–T012) after Phase 2. Tests T005–T008 [P] first, then T009 → T010 → T011 → T012.
- **US3** (T013–T015) after US1: it validates that US1 didn't change decisions. T015 is long; run it in the background while doing US2.
- **US2** (T016–T021) after T010 (`display`). T020 [P] can be written any time.
- **Polish** last. T024 must run before T025's Haiku re-run (V-6).

### Parallel Opportunities

- T003 with T002/T004.
- T005, T006, T007 and T008: same file but independent test functions, written together.
- T015 (stack, about 26 minutes) runs in the background during Phase 5.
- T020 and T022 (docs) in parallel with code tasks.

## Parallel Example: User Story 1

```text
Task: "T005 [US1] campaign-grain tests in tests/test_semantic_rules.py"
Task: "T006 [US1] grouped tests in tests/test_semantic_rules.py"
Task: "T008 [US1] capability + MCP tests in tests/test_semantic_rules.py"
```

## Implementation Strategy

1. **MVP = US1 + US3:** the rule lives in the data, and nothing the agent decides changes. That's already the fix the 005 measurement asked for.
2. **US2:** the audience sees it on screen in Block 2, with the instructor's talking point.
3. **Polish:** the validation doc. Re-run the Haiku measurement once 005 and 006 are both on `main`.

## Notes

- Commit after each phase on `006-awareness-roas-not-applicable`.
- The stack picks the change up through shared code: no `stack/` edit is expected (FR-008).
