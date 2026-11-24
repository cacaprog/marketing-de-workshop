# Roteiro do instrutor

**Workshop:** Construindo Dados Prontos para IA Agêntica — da ingestão à ação autônoma
**Caso:** agente de otimização de orçamento de mídia da *Aurora Cosméticos*
**Formato:** 1 dia (8h) ou 2 meios-períodos de 4h (quebra natural após o Bloco 2)
**Público:** squads mistos (1 perfil técnico + 1 perfil de negócio por dupla)

## Preparação (véspera)

```bash
uv sync --extra dev          # Python 3.11+
uv run agentready setup      # gera o cenário (âncora = agora)
uv run pytest -q             # 18 testes devem passar
```

- **Rode `agentready setup` no dia.** Os SLAs de frescor são relativos ao horário de geração.
- Terminal com fonte grande e largura ≥ 140 colunas (`export COLUMNS=140`).
- Ensaie `uv run agentready demo all` uma vez. Cada `Enter` avança uma etapa.
- Opcional (com rede): `ANTHROPIC_API_KEY` para `--brain claude`, e Phoenix para os traces (Bloco 4).

## Agenda (8h)

| Horário | Bloco | Teoria | Prática |
|---|---|---|---|
| 09:00 | **0 · Choque de realidade** | demo ao vivo | — |
| 09:30 | **1 · Fundação confiável** (contratos e quarentena) | 20 min | 45 min |
| 10:35 | intervalo | | |
| 10:50 | **2 · Camada de contexto** (semântica e métricas) | 20 min | 45 min |
| 11:55 | almoço | | |
| 12:55 | **3 · Do pesquisável ao acionável** (MCP e guardrails) | 25 min | 50 min |
| 14:10 | **4 · Rastreabilidade e governança** (traces e autonomia) | 20 min | 40 min |
| 15:10 | intervalo | | |
| 15:25 | **5 · Incidente e post-mortem** (dinâmica gamificada) | 15 min | 60 min |
| 16:40 | **Fechamento executivo** (maturidade e "segunda-feira") | | 30 min |
| 17:10 | encerramento | | |

---

## Bloco 0 · Choque de realidade (30 min)

**Comando:** `uv run agentready demo 0`

**Roteiro de fala**
1. "Este é o nosso agente. Ele tem uma missão simples: mover orçamento para onde o ROAS é melhor." Mostre o orçamento ANTES.
2. Rode o agente. Ele mostra o SQL que "escreveu" sozinho e o que viu: Meta com ROAS 0.
3. Ele pausa C03, C04 e C05 e joga R$ 11.500/dia no Google Marca.
4. Mostre a **verdade**: as campanhas da Meta tinham ROAS real de 4,1 e 5,8. São **~R$ 40 mil/dia de receita líquida em risco**.
5. Frase-âncora: *"Nenhum erro foi lançado. Nenhum alerta disparou."*
6. Dado de mercado: Precisely/Drexel LeBow 2026: 87% dos líderes dizem estar prontos para IA; 43% dizem que a prontidão dos dados é o maior obstáculo.

**Pergunta para a sala:** "Um analista humano teria pausado a Meta? Por quê não?" A resposta esperada é que ele estranharia o zero. É esse "teste do cheiro" que vamos codificar.

---

## Bloco 1 · Fundação confiável (65 min)

**Comando:** `uv run agentready demo 1`

**Teoria (20 min)**
- *Schema as law*: abra `contracts/conversions.odcs.yaml` e percorra tipo, `required`, `unique`, `minimum` e o domínio de valores (`metric: invalidValues` com `validValues`).
- SLA de frescor ligado ao `ingested_at` (última carga **bem-sucedida**), não ao timestamp do evento, e **por feed** (`customProperties → freshnessPartitionBy: source`).
- Quarentena (*dead-letter*): linhas ruins são desviadas e preservadas para investigação, nunca apagadas.
- Disjuntor por lote: >5% ruim derruba o lote inteiro, porque um lote 40% corrompido indica bug upstream e não ruído.
- Medalhão: humanos investigam Bronze, Silver e Quarentena; o agente consome **só a Gold**.

**Na demo, aponte:** 246 duplicados (o retry), o lote de 04/11 barrado (37% negativo), o meta_capi com 75h de atraso, e a Gold devolvendo **NULL** para a Meta. O agente agora diz *"Não possuo dados atuais"*.

**Prática (45 min) — ver `02-exercicios.md`, Bloco 1.** Exercício-chave para o perfil de negócio: **quem define o SLA de 24h e o que custa errá-lo?**

---

## Bloco 2 · Camada de contexto (65 min)

**Comando:** `uv run agentready demo 2`

**Teoria (20 min)**
- A tríade: **Domínio** (substantivos: campanha, pedido + regras), **Semântico** (números: medidas e métricas compiladas em SQL) e **Capacidades** (ações; Bloco 3). Tudo em `semantic/marketing.semantic.yaml`.
- Métricas como código: `ratio` é razão das somas; `derived` compõe outras métricas.
- Benchmark AtScale (estudo do fornecedor, 40 perguntas, TPC-DS): 20% → 92,5%. Use como direção, não como lei.

**Na demo, aponte:** a tabela "oficial vs 3 SQLs plausíveis". O fan-out (B) costuma ser o que mais impressiona, porque o número sai 100x menor. Depois, duas perguntas diferentes geram **o mesmo hash de SQL**.

**Prática (45 min) — Bloco 2 dos exercícios.** Destaque: criar a métrica `ticket_medio` e o debate de negócio "receita bruta ou líquida?".

> **Quebra para formato 2×4h:** termine o dia 1 aqui.

---

## Bloco 3 · Do pesquisável ao acionável (75 min)

**Comando:** `uv run agentready demo 3`

**Teoria (25 min)**
- O espectro de acesso no MCP: **Resources** (recuperação) → **Tools de leitura** (tempo real) → **Tools de escrita** (*write-back*).
- *Tool sprawl*: 5 capacidades de negócio, não 200 wrappers de endpoint.
- **"O texto recuperado informa, nunca autoriza."** A autorização mora em `config/guardrails.yaml`, no backend.
- Pré-condições avaliadas **no estado vivo**, na hora da execução. A fronteira de autonomia é definida pela reversibilidade (R0–R3).
- Trifeta letal (Simon Willison): dados privados + conteúdo não confiável + capacidade de agir. Aqui são as métricas, os briefings externos e a alteração de orçamento.

**Na demo, aponte:** o briefing do YouTube com a "nota do CMO". O agente (simulado como convencido) tenta R$ 35.000/dia e o backend recusa: `variacao_maxima` e `teto_do_portfolio`. Diga explicitamente: *"simulamos um modelo enganado; a defesa não pode depender do modelo resistir."*

**Ao vivo com rede (opcional):** `uv run agentready agent ready --brain claude`, ou conecte o servidor MCP ao Claude Desktop ou Claude Code (ver README) e peça "otimize o orçamento".

**Prática (50 min) — Bloco 3 dos exercícios.**

---

## Bloco 4 · Rastreabilidade e governança (60 min)

**Comando:** `uv run agentready demo 4`

**Teoria (20 min)**
- *Audit gap*: logs dizem **o que** foi acessado; a auditoria pergunta **por quê**.
- Linhagem agêntica: um trace por decisão, com spans por ferramenta. Cada span grava SQL, versões de contrato e semântica, pré-condições e o nível de autonomia.
- EU AI Act, arts. 12/19/26(6): registro automático e retenção ≥ 6 meses **para sistemas de alto risco**. O nosso caso provavelmente não é; use como padrão de boa prática. Brasil: LGPD e PL 2338/2023.
- Segurança: credenciais delegadas e efêmeras (JIT), menor privilégio. O servidor MCP só enxerga `ops.campaigns` e a Gold.
- Escada de autonomia: **shadow → supervisionado → autônomo com guardrails → total**, configurada **por ação** em `config/autonomy.yaml`.

**Na demo, aponte:** a árvore de spans, o HTML gerado em `traces/`, a cadeia de hash íntegra e a adulteração detectada. Mostre também a fila de aprovação: a aprovação reavalia as pré-condições, e a pausa (R2) sempre vai para humano. Feche com o modo shadow.

**Prática (40 min) — Bloco 4 dos exercícios** (o "interrogatório do auditor").

---

## Bloco 5 · Incidente e post-mortem sem culpados (75 min)

**Comando de demonstração:** `uv run agentready demo 5` (incidente "centavos")

**Teoria (15 min)**
- 5 pilares: **Frescor, Volume, Distribuição, Esquema, Linhagem**.
- **Contratos pegam o inválido; observabilidade pega o válido-mas-errado.**
- RCA com linhagem + 5 Porquês; TTD (tempo até detectar) e TTR (tempo até resolver).
- Cultura DRE/DataOps: o post-mortem é **sem culpados**. Pergunte "que sistema permitiu?", nunca "quem errou?".

**Dinâmica gamificada (60 min)** — papéis em `templates/raci.md`

1. Cada squad roda `uv run agentready demo 5 --incident random --no-pause` **ou**, para mais suspense, o *Incident Commander* roda `agentready backfill-meta` (se ainda houver backlog) e depois `agentready incident inject` **sem olhar o tipo**.
2. O Engenheiro de Dados investiga com `observe`, `health`, `quarantine`, `lineage --since "<injected_at>"` e `trace last`.
3. O Analista de Negócio usa `budgets` e `trace last` e responde: "que decisões o agente tomou com dado ruim? Qual o impacto em R$?"
4. Ao identificar a causa: `agentready incident detect` (marca o TTD). Corrigir com `rollback <CHG>` nas decisões contaminadas e `incident resolve` (marca o TTR).
5. Preencher `templates/post-mortem.md`. `agentready incident reveal` confirma o gabarito.

**Pontuação sugerida:** TTD (30%) · causa-raiz correta (30%) · decisões contaminadas revertidas (20%) · qualidade das ações corretivas (20%).

**Ações corretivas esperadas por incidente**

| Incidente | Pilar | O que o contrato fez | Ação corretiva esperada |
|---|---|---|---|
| centavos | Distribuição | **Nada** (passou) | `block_on_distribution_anomaly: true`; `maximum` em `order_value_brl`; teste de contrato no CI do produtor |
| renomeacao | Esquema | Barrou o lote → SLA estourou → agente parou | Contrato no CI do time de e-commerce (*breaking change* bloqueia deploy); versionamento do contrato |
| lote_duplicado | Volume | Barrou por chave duplicada | Idempotência no job upstream; alerta de volume |
| feed_parado | Frescor | — | Monitor de token, alerta de SLA para o dono do feed |

---

## Fechamento executivo (30 min)

Cada squad preenche `templates/autoavaliacao-maturidade.md` (Human-era → In Transition → Agent-ready) para a **própria empresa** e escolhe **os dois primeiros passos para segunda-feira**. Cada squad apresenta em 2 minutos.

**Mensagem final:** o agente da manhã e o da tarde usam a *mesma lógica de decisão*. O que mudou foi a **arquitetura de dados ao redor dele**.
