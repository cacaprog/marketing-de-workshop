# Implementation Plan: Model Comparison With and Without the Context Layer

**Branch**: `005-model-comparison` | **Date**: 2026-11-27 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/005-model-comparison/spec.md`

## Summary

Let any language model sit in the agent's seat (Claude through the API, or a local model on Ollama or llama.cpp) and run it in two conditions on the same freshly regenerated scenario: **sem contexto** (raw Bronze through a read-only SQL sandbox, raw briefings, direct writes) and **com contexto** (today's governed capabilities). A new `agentready compare` command runs brains × conditions × N runs and scores each run against the scenario's ground truth. For the live session, `agentready perguntas` shows 8 predefined business questions answered side by side with and without the context layer, each checked against the official answer, and can replay a recorded run offline; `agentready chat` offers a free read-only conversation in either condition.

Technical approach (from [research.md](research.md)):
- the current Claude loop becomes one provider-neutral loop with two small adapters: Anthropic (unchanged call options) and an OpenAI-style chat-completions adapter written with the standard library;
- tools are declared once per condition;
- the conditions map onto the existing `NaiveAgent` and `ReadyAgent`, so the rules brain's paths stay byte-for-byte the same;
- scoring reads state diffs, change-log rows and approval requests, so every brain is scored the same way;
- business questions live in `config/perguntas.yaml` as rules, not numbers: each official answer is resolved from the semantic layer, source health or a domain rule at run time; the model answers through one typed `responder` tool in both conditions, so verdicts are deterministic (R14–R17).

## Technical Context

**Language/Version**: Python ≥ 3.11 (project standard)

**Primary Dependencies**: existing only: duckdb, pyyaml, rich, mcp, opentelemetry-sdk; `anthropic` stays in the optional `llm` extra. Local servers are reached with `urllib.request` (standard library). No new dependency.

**Storage**: the existing DuckDB warehouse (`data/warehouse.duckdb`), regenerated per comparison run; a per-run in-memory DuckDB sandbox for the sem-contexto SQL tool; results as JSON under `data/compare/` (git-ignored).

**Testing**: pytest, offline. A scripted model adapter, plus a standard-library HTTP stub that speaks the OpenAI-style protocol on localhost.

**Target Platform**: the participant's machine (Linux/macOS/Windows), no containers; Ollama ≥ 0.31 or a llama.cpp `llama-server` for local brains.

**Project Type**: CLI tool plus library (`agentready` package).

**Performance Goals**:
- Rules runs take under 5 s each, including the scenario rebuild.
- Language-model runs are bounded by the model: 12 turns at most, with a 300 s timeout per call by default.
- A full comparison is minutes to tens of minutes, and its progress is printed per run.

**Constraints**:
- Offline by default.
- The demo output is unchanged.
- The decision rules are unchanged.
- The stack track is untouched apart from the shared instruction text.
- All user-facing text is in pt-BR.

**Scale/Scope**: 6 campaigns; 8 business questions; up to ~10 brains × 2 conditions × 20 runs per comparison. 5 new modules, 1 new config file, 4 edited modules; about 25 new tests.

## Constitution Check

*GATE: checked before Phase 0 research and again after Phase 1 design.*

| Principle | Before research | After design |
|---|---|---|
| **I. The agent is the constant** | Pass. The conditions differ only in data and tools. `_rules` and the rules `NaiveAgent` path are unchanged, and the stack runs the same agent source. | Pass. `NaiveAgent`/`ReadyAgent` take a brain spec; a language-model brain runs the same `LLMBrain` loop and instruction in both conditions (R4, R5). The neutral instruction applies to every track's Claude brain at once, with no fork. |
| **II. Safety lives in the backend** | **Exception.** Sem-contexto writes skip preconditions, guardrails and the ladder. Question mode and chat are read-only (no exception). | Exception justified below. The governed path is unchanged. Direct writes are confined to `agent naive --brain <llm>` and `compare`, always labelled "ANTES", logged with actor and justification, and reversible by rollback. No R3 tool, and nothing is added to MCP (R7). |
| **III. Missing data is unknown** | Pass. No change to Gold or the semantic layer. | Pass. The sem-contexto condition deliberately exposes only raw data, which is the Block 0 lesson. Scoring counts actions on stale data. |
| **IV. Deterministic and offline by default** | Pass. Rules stays the default, and language-model brains are opt-in. | Pass. All tests use a scripted adapter or a localhost stub. `compare` and `perguntas` never run inside `demo`. On stage, the questions are shown from a recorded run replayed offline (R16). |
| **V. One test per promise** | Pass, with a plan to add tests. | Pass. Each FR has a test (see the test map in tasks); the 18 existing tests are not edited. |
| **VI. Every tool replaces a module** | Pass. No new framework. | Pass. No new dependency (R1). The OpenAI SDK and LiteLLM were rejected. |
| **VII. Accurate claims** | Pass, with a plan. | Pass. The guide states run-to-run variance and that a few runs illustrate rather than measure. No model is called "recommended" before V-0 (R12). The question set includes a control question both conditions can get right, and replays show when and with which model they were recorded. |
| **Materials pt-BR / config single source** | Pass. | Pass. The Claude model stays `AGENTREADY_MODEL` in one place. Local settings are four env vars that CLI flags override. |

## Project Structure

### Documentation (this feature)

```text
specs/005-model-comparison/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── cli.md
│   ├── toolsets.md
│   └── results-file.md
├── checklists/requirements.md
└── tasks.md              # /speckit-tasks
```

### Source Code (repository root)

```text
src/agentready/
├── agent.py          # EDIT: ClaudeBrain → LLMBrain (provider-neutral loop); neutral SYSTEM;
│                     #       NaiveAgent/ReadyAgent accept a brain spec; rules paths unchanged
├── llm.py            # NEW: BrainSpec parsing, ModelTurn, AnthropicChat, OpenAICompatChat (urllib), errors
├── toolsets.py       # NEW: ToolSpec, Toolset; COM_CONTEXTO (wraps capabilities); SEM_CONTEXTO
│                     #      (in-memory SQL sandbox, raw briefing, direct writes + change log)
├── compare.py        # NEW: runner (regenerate per run, probe, skip), GroundTruth, scoring, summary, JSON file
├── perguntas.py      # NEW: question set loader + resolver, verdicts, side-by-side panels, replay, chat loop
├── capabilities.py   # EDIT (1 line): public alias log_change = _log_change
├── cli.py            # EDIT: --brain local, --llm-model, --llm-url, --request on agent; new compare, perguntas, chat commands
└── ui.py             # EDIT: comparison table renderer (pt-BR)

tests/
├── test_workshop.py  # unchanged
├── test_policy.py    # unchanged
├── fake_llm.py       # NEW: ScriptedChat + OpenAI-style HTTP stub (test helpers)
├── test_brains.py    # NEW: LLMBrain with scripted turns; tool-call failures; unreachable server; adapters
├── test_toolsets.py  # NEW: sandbox allowlist/refusals/row cap; direct writes logged + rollback; no R3; MCP unchanged
├── test_compare.py   # NEW: rules reference scores (R8 values); scripted model scores; skip; results file
└── test_perguntas.py # NEW: resolver matches R14; each question discriminates (SC-008); verdict rules; replay offline; chat read-only

config/
└── perguntas.yaml           # NEW: the 8 business questions and their official-answer rules

docs/
├── 06-comparar-modelos.md   # NEW: pt-BR guide (Ollama, llama.cpp :8081, compare, reading the table, limits)
└── 01-roteiro-do-instrutor.md  # EDIT: Block 2 note on the business questions (replay); optional note after Blocks 0 and 3
README.md                    # EDIT: commands table
.gitignore                   # EDIT: data/compare/
```

**Structure Decision**: single project, the existing `src/agentready` package and `tests/`. The stack track (`stack/`) is not touched. Its CLI keeps `--brain rules|claude`, and its Claude brain picks up the neutral instruction through the shared source.

## Phase 0 / Phase 1 outputs

- [research.md](research.md): R1–R17. Open facts are marked "to verify in V-0" (Ollama context length, llama.cpp flags and probe, which installed models call tools, DuckDB statement-type API).
- [data-model.md](data-model.md): BrainSpec, Condition, ToolSpec/Toolset, ModelTurn, Run, Change/Request, GroundTruth, Score, Comparison.
- [contracts/](contracts/): CLI, toolsets plus the shared instruction, results files plus tables, business question set.
- [quickstart.md](quickstart.md): V-0 spike, then V-1…V-12 validation.

## Complexity Tracking

| Violation / added complexity | Why needed | Simpler alternative rejected because |
|---|---|---|
| **Principle II**: sem-contexto tools write to `ops.campaigns` with no precondition, guardrail or ladder | The comparison has to show what a model does with no context layer. That is the Block 0 "before", which `NaiveAgent` already does with hand-written rules. | Shadow-only writes would hide the harm being measured. A "guardrails off" switch inside `capabilities.py` would put a bypass into the governed path. A separate, labelled toolset is the smaller risk: local scenario only, logged with actor, reversible, never exposed through MCP. |
| Shared-code edit: `ClaudeBrain` becomes `LLMBrain` with provider adapters | FR-003 requires one loop, instruction and turn limit for every model. | A second loop for OpenAI-style servers would drift from the Claude one. |
| Shared-code edit: neutral system instruction (FR-010, option A) | Attributes any difference to the context layer, not the prompt. | Keeping today's instruction (option B) mixes prompt and data effects; rejected by the user. |
| `compare` and `perguntas` regenerate the main warehouse | Every run must see identical data (FR-014). | A separate warehouse file needs patching the DB path that several modules bind at import time. The command warns and asks before starting instead. |
