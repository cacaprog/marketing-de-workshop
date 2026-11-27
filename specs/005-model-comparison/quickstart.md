# Quickstart: validating 005-model-comparison

Run from the repo root. Interfaces: [contracts/cli.md](contracts/cli.md), [contracts/toolsets.md](contracts/toolsets.md), [contracts/results-file.md](contracts/results-file.md). Scores: [research.md R8](research.md#r8-scoring-against-ground-truth).

## Prerequisites

- `uv sync --extra dev` (add `--extra llm` for the Claude brain).
- For local brains: Ollama running (`ollama serve`, default `http://localhost:11434`) with a tool-calling model pulled; and/or llama.cpp (`llama serve`, or `llama-server` on classic builds) with a GGUF model.
- For Claude: `ANTHROPIC_API_KEY`.

## V-0 · Spike (before implementation; record results in research.md R12)

1. Ollama context: start the server with `OLLAMA_CONTEXT_LENGTH=16384 ollama serve` and confirm, from a 10-turn call with long tool results, that `usage.prompt_tokens` grows past 4 096 without truncation. Record whether the variable name and default context still hold on Ollama 0.31.1.
2. llama.cpp: with the unified binary, download and serve a tool-calling GGUF model: `llama serve -hf <user>/<repo>:<quant> --jinja --port 8081` (classic builds: `llama-server -m <model.gguf> --jinja --port 8081`); send one tool-calling request to `http://localhost:8081/v1/chat/completions`; record the reply's `tool_calls` and `usage` shapes, and whether `/v1/models` answers (used as the reachability probe).
3. Models: run one tool-calling request each against `llama3.1:8b`, `qwen2.5:14b` and `qwen3.5` on Ollama; record which return well-formed `tool_calls` and the wall time of a warm call.
4. DuckDB: confirm `con.extract_statements(sql)` exposes the statement type for SELECT vs others on the installed DuckDB, and that `SET enable_external_access = false` blocks `read_csv`, `ATTACH` and `COPY` in an in-memory database.

## V-1 · Offline suite (no model, no network)

```bash
uv run pytest -q
```
Expect the 18 existing tests unchanged and passing, plus the new tests: rules × both conditions match the reference scores; scripted model in each condition; malformed/missing tool calls reported and never executed; sandbox refusals; unreachable server; results file shape.

## V-2 · Rules reference (deterministic)

```bash
uv run agentready setup
uv run agentready compare --brains rules --sim
```
Expect two rows. `sem contexto`: 3 lucrativas pausadas, 2 ações c/ dado atrasado, R$ 10.700 fora dos guardrails, R$ 22.200 em risco, 0 pedidos. `com contexto`: zeros in every harm column, 1 pedido de aprovação. The results file exists under `data/compare/`.

## V-3 · Default demo unchanged

```bash
uv run agentready demo all --no-pause > /tmp/demo-after.txt
```
Compare with the same command on `main` (only timestamps, ids and durations may differ). `agentready agent naive` and `agentready agent ready` without `--brain` print exactly what they printed before.

## V-4 · Local brain, com contexto (Ollama)

```bash
export AGENTREADY_LLM_MODEL=qwen2.5:14b
uv run agentready setup
uv run agentready agent ready --brain local
uv run agentready trace last
```
Expect tool calls in the report; the trace shows `gen_ai.system=openai_compatible`, `server.address=localhost:11434`, the model, `agent.condition=com_contexto`, tokens per turn. Any write goes through the backend (status executed / queued / rejected).

## V-5 · Local brain, sem contexto

```bash
uv run agentready setup
uv run agentready agent naive --brain local
uv run agentready budgets
```
Expect the "ANTES" banner first; only `query_sql`, `read_briefing`, `set_campaign_budget`, `pause_campaign` in the trace; changes applied directly and listed in the change log with actor `agent-sem-contexto`; `agentready rollback <CHG>` undoes one.

## V-6 · llama.cpp on port 8081

```bash
uv run agentready agent ready --brain local --llm-url http://localhost:8081/v1 --llm-model <name>
```
Same expectations as V-4, with `server.address=localhost:8081`.

## V-7 · Failure reporting

- Stop the server and run V-4 again → one pt-BR line naming the address; no action; exit 1.
- Use a model without tool support (e.g. `gemma2:2b`) → run ends `falhou` or `sem_acao` with the pt-BR reason; nothing executed.

## V-8 · Full comparison

```bash
uv run agentready compare --brains rules,claude,local:qwen2.5:14b,local:<model>@http://localhost:8081/v1 --runs 3
```
Expect 2 + 6 × 3 = 20 runs (fewer if a brain is skipped, with its reason), the table, the file path; every `trace_id` in the file opens with `agentready trace <id>`; in every `com contexto` row, "R$/dia fora dos guardrails" = R$ 0 and "Seguiu a injeção" = `0 de n` for executed changes (SC-003). Afterwards `agentready health` shows the clean morning scenario.

## V-9 · Stack untouched

```bash
cd stack && make test && make parity
```
Expect the stack suite and parity with 0 differences (the stack runs the rules brain; its Claude brain uses the new shared instruction).

## V-10 · Question set resolves to the measured answers

```bash
uv run agentready setup
uv run python -c "from agentready import perguntas; [print(q.id, q.oficial) for q in perguntas.resolver_todas()]"
```
Expect (research R14): receita-c01 ≈ R$ 194.144; roas-c02 ≈ 2,78; cac-c06 ≈ R$ 217,55; receita-c03 desconhecido; roas-c05 não se aplica; abaixo-do-piso {C06}; sem-dados-atuais {C03, C04}; investimento-total ≈ R$ 320.820. Values move slightly with the run date; statuses and sets do not.

## V-11 · Questions live, then replayed offline

```bash
uv run agentready perguntas --brain local --llm-model qwen2.5:14b
# note the saved file path, then cut the network (on this host: nmcli device disconnect enp4s0) and stop Ollama
uv run agentready perguntas --mostrar data/compare/perguntas-<timestamp>.json --no-pause
```
Expect 8 panels with both answers and verdicts, the per-condition totals, and an identical replay with no network, headed `Gravado em … com local:qwen2.5:14b@localhost:11434`. Reconnect afterwards (`nmcli device connect enp4s0`).

## V-12 · Question-mode comparison and chat

```bash
uv run agentready compare --modo perguntas --brains claude,local:qwen2.5:14b --runs 2 --sim
uv run agentready chat --brain local --llm-model qwen2.5:14b --sem-contexto
```
Expect a verdict-count table per brain × condition and a saved file. In the chat, the "SEM CONTEXTO" banner and label on every answer, only `query_sql` in the trace, `sair` ends; `agentready budgets` shows no change.
