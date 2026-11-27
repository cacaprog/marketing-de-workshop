# Contract: CLI

All user-facing output in pt-BR. Exit code 0 on success, 1 on a usage or configuration error, 2 when every brain in a comparison was skipped or failed.

## `agentready agent naive|ready`

```
agentready agent naive [--brain rules|claude|local] [--llm-model M] [--llm-url URL] [--request "..."]
agentready agent ready [--brain rules|claude|local] [--llm-model M] [--llm-url URL] [--gullible] [--request "..."]
```

- `--brain` default `rules`: output and behaviour as today for `naive` and `ready` (only timestamps, ids and durations differ between runs).
- `naive` with a language-model brain = condition **sem contexto**; every run prints, before anything else: `ANTES: agente sem a camada de contexto — lê a Bronze e escreve direto na plataforma, sem guardrails.`
- `ready` with a language-model brain = condition **com contexto**.
- `--llm-model` / `--llm-url` override `AGENTREADY_LLM_MODEL` / `AGENTREADY_LLM_BASE_URL`; they apply only to `--brain local`.
- `--gullible` applies only to the rules brain (unchanged); with another brain it is refused: `--gullible simula um agente convencido; só vale com --brain rules.`
- Errors before the run (no model, server unreachable, missing Claude key) print one pt-BR line naming what is missing and how to fix it, and exit 1 without acting.

## `agentready compare`

```
agentready compare --brains SPEC[,SPEC...] [--runs N] [--condicoes ambas|com|sem] [--llm-url URL] [--sim]
```

- `SPEC`: `rules` · `claude` · `claude:<model>` · `local:<model>` · `local:<model>@<url>` (split on the last `@`). `--llm-url` is the default URL for `local` specs without one.
- `--runs` default 3, min 1, max 20. The rules brain always runs once per condition.
- `--condicoes` default `ambas`.
- Before starting, prints the plan (brains, conditions, total runs) and the warning `A comparação recria o cenário a cada execução (como o setup).`; asks for confirmation unless `--sim` is given. A Claude brain in the plan adds: `Usa a API da Anthropic (cobrada por token).`
- During the run: one progress line per run (`[3/14] local:qwen2.5:14b · sem contexto · 2/3 … ok (4 ações, 71 s)`).
- At the end: the summary table ([results-file.md](results-file.md), "Tabela"), the skipped brains with reasons, and the path of the results file.
- The scenario is regenerated once more at the end; no approval is decided by the command.

## `agentready perguntas`

```
agentready perguntas --brain rules|claude|local [--llm-model M] [--llm-url URL] [--ids id1,id2] [--no-pause] [--sim]
agentready perguntas --mostrar data/compare/perguntas-YYYYMMDD-HHMMSS.json [--ids …] [--no-pause]
```

- Live mode prints `As perguntas recriam o cenário (como o setup): o estado da demonstração ao vivo será perdido.` and asks for confirmation unless `--sim` is given (plus the Claude cost line when the brain is Claude). `--mostrar` never touches the scenario.
- Regenerates the scenario once, then for each question runs "sem contexto" and "com contexto" and shows the panel below; Enter advances unless `--no-pause`.
- `--brain rules` is refused: `as perguntas precisam de um modelo de linguagem; para a camada semântica determinística use agentready ask.`
- `--mostrar` replays a saved run with no model, network or credential. The header reads `Gravado em <data> com <cérebro>`.
- Panel per question:

```
Pergunta 1/8 · Qual foi a receita líquida da campanha Google Search - Marca (C01) nos últimos 7 dias?
Resposta oficial: R$ 194.144
┌ sem contexto ───────────────────────┐ ┌ com contexto ───────────────────────┐
│ R$ 244.955                          │ │ R$ 194.144                          │
│ "somei order_value_brl da Bronze"   │ │ "receita líquida, camada semântica" │
│ ERRADA                              │ │ CERTA                               │
└─────────────────────────────────────┘ └─────────────────────────────────────┘
O que mostra: Receita é sempre líquida; linhas duplicadas e inválidas ficam na quarentena.
```
  (values illustrative) — at the end, one line per condition: `sem contexto: 1 certa · 0 desconhecido correto · 5 erradas · 2 inventou número`.
- Saves `data/compare/perguntas-YYYYMMDD-HHMMSS.json` ([results-file.md](results-file.md)).

## `agentready compare --modo perguntas`

```
agentready compare --modo perguntas --brains SPEC[,SPEC...] [--runs N] [--sim]
```

Same brain specs and skipping rules as the action comparison; `rules` is skipped with the reason above. Table: one row per brain × condition with the count (mean over runs) of each verdict.

## `agentready chat`

```
agentready chat --brain claude|local [--sem-contexto] [--llm-model M] [--llm-url URL]
```

- Banner: `Conversa com <cérebro> · COM CONTEXTO (métricas oficiais e saúde dos dados)` or `· SEM CONTEXTO (dados brutos da Bronze)`.
- Each answer is prefixed with the condition label; `sair` or Ctrl-D ends; no writes are possible.
