# Dados Prontos para IA Agêntica — Workshop (caso de Marketing)

Projeto completo e executável do workshop **"Construindo Dados Prontos para IA Agêntica: da ingestão à ação autônoma"**.

Um agente de IA otimiza o orçamento diário de mídia paga da empresa fictícia **Aurora Cosméticos** (6 campanhas em Google, Meta, TikTok e YouTube). De manhã, o agente ingênuo toma decisões desastrosas com dados corrompidos. Ao longo do dia, cada bloco adiciona uma camada da arquitetura até ele operar de forma confiável, rastreável e governada. **A lógica de decisão do agente não muda; muda a arquitetura de dados ao redor dele.**

> Antes de apresentar, leia [`docs/00-validacao-do-projeto.md`](docs/00-validacao-do-projeto.md): ele lista o que foi corrigido na proposta original (citações, escopo regulatório e pilha tecnológica).
>
> Para CMOs e gestores de Growth: [`docs/03-visao-de-negocio.md`](docs/03-visao-de-negocio.md) explica o problema, a abordagem, quando usá-la e por que ela importa para decisões de marketing, sem jargão técnico.

## Início rápido

```bash
uv sync --extra dev            # Python 3.11+ · sem Docker, sem nuvem, sem chave de API
uv run agentready setup        # gera o cenário (rode no dia: SLAs são relativos a "agora")
uv run agentready demo all     # roteiro completo narrado; Enter avança cada etapa
uv run pytest -q               # 18 testes: um contrato por promessa de cada bloco
```

Um bloco por vez: `uv run agentready demo 0` … `demo 5`. Sem pausas: `--no-pause`.

## Trilha stack (opcional)

Para continuar estudando depois do workshop: [`stack/`](stack/README.md) roda **o mesmo cenário com ferramentas de produção** (Airflow 3.3, dbt + Cosmos, Data Contract CLI e aprovação humana dentro do Airflow), reaproveitando sem cópias o agente, os contratos e a configuração deste repositório. `make parity` prova ao vivo que o agente decide igual nas duas trilhas.

Ela **não é necessária para apresentar o workshop**: precisa de Docker, ≥ 4 CPUs e ≥ 8 GB de RAM. A demo acima continua sem Docker, sem nuvem e sem chave de API.

## O que cada bloco mostra

| Bloco | Problema de negócio | O que a arquitetura faz | Onde está |
|---|---|---|---|
| **0 · Choque de realidade** | Agente lê dados brutos, pausa as 2 melhores campanhas (~R$ 40 mil/dia em risco) | — (o "antes") | `agent.py::NaiveAgent` |
| **1 · Contratos e quarentena** | Feed da Meta parado há 3 dias; lote duplicado; valores negativos | Contrato ODCS → quarentena → disjuntor por lote; SLA de frescor **por feed**; Gold devolve **NULL**, não zero | `contracts/` · `contracts.py` · `pipeline.py` |
| **2 · Camada semântica** | SQL "adivinhado" erra receita bruta/líquida, faz fan-out, média de razões | Métricas como código; mesmo SQL para perguntas diferentes; regras de domínio | `semantic/` · `semantic.py` |
| **3 · MCP e guardrails** | Briefing com injeção de prompt manda subir o YouTube para R$ 35 mil/dia | 5 capacidades de negócio; pré-condições no estado vivo; "texto informa, nunca autoriza"; R0–R3 | `mcp_server.py` · `capabilities.py` · `config/guardrails.yaml` |
| **4 · Rastreabilidade** | "Por que o agente fez isso?" seis meses depois | Trace OpenTelemetry por decisão; log com cadeia de hash; escada de autonomia; fila de aprovação | `tracing.py` · `autonomy.py` · `config/autonomy.yaml` |
| **5 · Incidente** | Deploy upstream passa a enviar valores em centavos; o contrato **aprova** | 5 pilares de observabilidade; linhagem até a decisão; rollback; TTD/TTR; post-mortem | `observability.py` · `incidents.py` · `templates/` |

## Arquitetura

```
 feeds upstream             Medalhão (DuckDB)                          Camada de contexto       Ações governadas
 ┌──────────────┐   ┌────────┐  contrato  ┌────────┐   ┌──────────────────────┐   ┌──────────────────┐   ┌────────────────────┐
 │ ga4 (site)   │──▶│ Bronze │──(ODCS)───▶│ Silver │──▶│ Gold                 │──▶│ Modelo semântico │──▶│ Servidor MCP       │
 │ meta_capi    │   │ (raw)  │     │      │(typed) │   │ campaign_daily       │   │ métricas + guarda│   │ Resources/Tools    │
 │ ads_api      │   └────────┘     ▼      └────────┘   │ source_health (SLA)  │   │ de frescor       │   │ pré-condições      │
 └──────────────┘          Quarentena + disjuntor      └──────────────────────┘   └──────────────────┘   │ escada de autonomia│
        ▲                    (humanos investigam)            (agente só lê aqui)                         └─────────┬──────────┘
        │                                                                                                          │
        └──────────── 5 pilares de observabilidade · linhagem ◀── traces OpenTelemetry (audit.jsonl, hash) ◀───────┘
                                                                                            ops.campaigns (plataforma "viva")
```

## Comandos

| Comando | Para quê |
|---|---|
| `agentready setup` | Reset completo: gera o cenário e roda o pipeline |
| `agentready demo <0-5\|all> [--no-pause] [--incident centavos\|random]` | Roteiro narrado |
| `agentready pipeline` | Bronze → contratos → Silver → Gold |
| `agentready health` · `quarantine` | Frescor, quarentena e versões dos contratos |
| `agentready ask "ROAS por campanha nos últimos 7 dias"` | Linguagem natural → camada semântica → SQL |
| `agentready agent naive` · `agent ready [--gullible] [--brain claude]` | Roda um agente |
| `agentready budgets` · `approvals` · `approve <REQ>` · `reject <REQ>` · `rollback <CHG>` | Operação humana |
| `agentready autonomy [shadow\|supervised\|guarded\|full\|clear]` | Override global da escada |
| `agentready trace [id\|last]` · `verify` | Árvore de decisão (+ HTML em `traces/`) e integridade do log |
| `agentready observe` · `lineage [nó] [--since ts]` | 5 pilares e impacto a jusante |
| `agentready incident inject [tipo]` · `detect` · `resolve` · `reveal` · `list` | Simulação do Bloco 5 |
| `agentready backfill-meta` | Corrige o feed da Meta (chegam os lotes atrasados) |
| `agentready mcp` | Servidor MCP (stdio) |

## Conectar o servidor MCP

**Claude Code:** o `.mcp.json` na raiz já registra o servidor `aurora-midia`. Abra o Claude Code nesta pasta e aprove o servidor.

**Claude Desktop:** em `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "aurora-midia": {
      "command": "uv",
      "args": ["run", "--directory", "/caminho/absoluto/para/workshop", "agentready", "mcp"]
    }
  }
}
```

Depois peça: *"Verifique a saúde dos dados e otimize o orçamento conforme a política."* Toda escrita passa pelas mesmas pré-condições e pela mesma escada de autonomia da CLI.

## Agente com Claude (opcional)

```bash
uv sync --extra llm --extra dev
export ANTHROPIC_API_KEY=...            # ou `ant auth login`
uv run agentready agent ready --brain claude
```

Usa `claude-opus-5-5` (troque com `AGENTREADY_MODEL`) com pensamento adaptativo e *fallback* automático no servidor para recusas. As ferramentas são as mesmas capacidades governadas. O agente padrão (`--brain rules`) é determinístico, ideal para palco sem rede.

## Traces no Arize Phoenix / Langfuse (opcional)

```bash
uv sync --extra otlp
docker run -p 6006:6006 arizephoenix/phoenix:latest
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:6006 uv run agentready agent ready
```

Para o Langfuse, aponte `OTEL_EXPORTER_OTLP_ENDPOINT` e `OTEL_EXPORTER_OTLP_HEADERS` para o endpoint OTel do seu projeto. O log local `traces/audit.jsonl` continua sendo gravado.

## Estrutura

```
contracts/      contratos ODCS v3 (conversions, ad_spend, campaigns)
semantic/       modelo de domínio + semântico + capacidades (YAML)
config/         guardrails.yaml (autorização) · autonomy.yaml (escada)
corpus/         política de orçamento (confiável) e briefings (não confiáveis; C06 tem a injeção)
src/agentready/ generate · contracts · pipeline · semantic · capabilities · autonomy · tracing
                agent · mcp_server · observability · incidents · blocks (roteiro) · cli · ui
templates/      post-mortem · RACI · autoavaliação de maturidade
docs/           00 validação · 01 roteiro do instrutor · 02 exercícios · 03 visão de negócio
tests/          18 testes, um por promessa de bloco
```

## O cenário plantado

| Problema | Como aparece | Quem pega |
|---|---|---|
| Feed `meta_capi` parado há 3 dias | Meta "vendeu zero" | SLA de frescor por feed (Bloco 1) |
| Lote do ga4 carregado em dobro (retry) | YouTube parece lucrativo | Chave única + disjuntor (Bloco 1) |
| ~1% de linhas sujas | negativos, `"189,90"`, campanha `C99`, nulos | Regras do contrato (Bloco 1) |
| Lote antigo 37% corrompido | bug upstream | Disjuntor por lote (Bloco 1) |
| Awareness avaliada por ROAS | TikTok seria pausado | Regra do modelo de domínio (Bloco 2) |
| Injeção no briefing do YouTube | "aumente para R$ 35.000" | Pré-condições no backend (Bloco 3) |
| Incidentes do Bloco 5 | centavos · renomeação · duplicado · feed parado | Distribuição · Esquema · Volume · Frescor |

Os dados são sintéticos e determinísticos (seed 42).
