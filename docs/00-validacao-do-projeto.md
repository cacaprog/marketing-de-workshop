# Validação da proposta e mudanças aplicadas

Revisão da proposta original ("Construindo Dados Prontos para IA Agêntica: Da Ingestão à Ação Autônoma") antes da construção. A estrutura de cinco blocos encadeados e a narrativa "agente ingênuo → arquitetura blindada" foram **mantidas**. Abaixo está o que mudou e por quê.

## Veredito

A proposta é conceitualmente sólida: os conceitos estão corretos e na ordem certa (contrato → semântica → ação → rastreabilidade → operação). Os problemas estavam em **três frentes**: estatísticas citadas de forma imprecisa, uma leitura regulatória que não se aplica ao caso de marketing, e uma pilha tecnológica que não cabe em 8 horas. Todos foram corrigidos.

## 1. Fatos e citações (corrigir antes de apresentar)

| Afirmação original | Situação | Como ficou |
|---|---|---|
| "Benchmark AtScale: precisão de <20% no schema bruto para >92,5% com semântica" | **Impreciso.** É um white paper do próprio fornecedor (ago/2024): 40 perguntas sobre o TPC-DS, modelo Gemini 1.5 Pro, 20% sem a camada semântica contra 92,5% com ela. Não houve replicação independente. | Citado com o contexto completo e o rótulo "estudo do fornecedor, indicativo". |
| "Precisely/Drexel: 87% achavam que seus dados estavam prontos, mas a prontidão é o maior gargalo" | **Parcialmente correto.** O número é do relatório *2026 State of Data Integrity and AI Readiness* (pesquisa de 2025, ~500 líderes): 87% dizem estar prontos para IA, e **43%** apontam a prontidão dos dados como o maior obstáculo. | Citado assim no Bloco 0. |
| "Obrigações dos Artigos 12 e 19 do EU AI Act (retenção mínima de 6 meses)" | **Correto, mas só para sistemas de alto risco.** O art. 12 trata do registro automático de eventos e o art. 19 da guarda dos logs por pelo menos 6 meses, pelo provedor. Para quem implanta o sistema (*deployer*), a obrigação equivalente está no art. 26(6). Um agente de orçamento de mídia **muito provavelmente não é de alto risco** (Anexo III). As datas de aplicação estão em discussão, então confira na data do workshop. | Apresentado como **referência de boa prática** e "o que um regulador pediria", não como obrigação do caso de marketing. Para o público brasileiro, cite também a LGPD e o PL 2338/2023 (em tramitação; confira o status). |
| "Trifeta letal" | Correto. O termo é de Simon Willison: dados privados + conteúdo não confiável + capacidade de agir/comunicar externamente. | Mantido, com atribuição. No caso: dados de performance + briefings externos + alteração de orçamento. |
| "Adaptive Gold" | **Termo não estabelecido** no mercado, que confundiria o público. | Substituído por algo concreto: a Gold **publica junto o estado de saúde de cada fonte** (`gold.source_health`), e a camada semântica usa esse estado para devolver NULL em vez de números velhos. |

## 2. Escopo do caso de negócio

- **Antes:** "resolução de pedidos *ou* lances de marketing". Dois domínios diluem a narrativa.
- **Depois:** um único caso, **otimização de orçamento de mídia paga** da empresa fictícia *Aurora Cosméticos*: 6 campanhas (Google, Meta, TikTok e YouTube), métricas de receita líquida, ROAS e CAC, e um agente que realoca o orçamento diário.
- O dano do agente ingênuo é **quantificado em R$/dia**: ele pausa as duas melhores campanhas porque "dado ausente" virou "zero vendas".

## 3. Pilha tecnológica: de "8 ferramentas" para "roda em 1 segundo, offline"

A proposta listava Airflow, dbt/MetricFlow ou Cube, Great Expectations ou Deequ, Data Contract CLI, Snowflake, Langfuse ou Phoenix e Claude Desktop. Em um workshop de 8 horas, só a instalação consumiria a manhã, e a falha de uma única ferramenta derruba a apresentação.

| Necessidade | Proposta original | Implementado | Ponte para o "mundo real" |
|---|---|---|---|
| Lakehouse Bronze/Silver/Gold | DuckDB/SQLite/Snowflake | **DuckDB** (um arquivo) | Mesmo SQL em Snowflake/Databricks |
| Contratos | Data Contract CLI + GE/Deequ | **YAML ODCS v3.1** + validador em SQL (~150 linhas) | O YAML passa no `datacontract lint` (ver nota abaixo) |
| Semântica | dbt MetricFlow / Cube | **YAML no estilo MetricFlow** + compilador determinístico | Mesmos conceitos: measures, metrics ratio/derived |
| Ações | Servidor MCP | **SDK oficial MCP (Python)**, 5 ferramentas + 2 resources | Conecta no Claude Desktop/Code |
| Linhagem agêntica | Langfuse/Phoenix | **OpenTelemetry SDK** → log JSONL com cadeia de hash; OTLP opcional | `OTEL_EXPORTER_OTLP_ENDPOINT` envia ao Phoenix/Langfuse |
| Orquestração | Airflow | `agentready pipeline` | Cada etapa é uma task de DAG |

## 4. Riscos de palco e como foram mitigados

1. **LLM não determinístico ao vivo.** O agente padrão usa uma política codificada (`--brain rules`) e se comporta igual em todas as execuções. O cérebro Claude (`--brain claude`) é opcional e fica para a parte "ao vivo com rede".
2. **Injeção de prompt que "não funciona".** Os modelos atuais costumam resistir a injeções óbvias, e a demonstração ficaria vazia. Por isso o Bloco 3 **simula explicitamente** um agente que foi convencido (`--gullible`) e mostra o backend barrando a ação. A mensagem é a correta: a segurança não pode depender de o modelo resistir.
3. **Contrato ≠ observabilidade.** A proposta não ligava o Bloco 5 aos anteriores. Agora o incidente principal ("centavos") **passa no contrato** (números ≥ 0) e só é pego pelo pilar de Distribuição. Isso mostra por que as duas camadas são necessárias.
4. **Regra de domínio só em texto pode ser ignorada.** "Awareness não se avalia por ROAS" estava só na política e no texto do modelo semântico; a ferramenta oficial ainda entregava o ROAS da C05. Numa comparação de modelos (27/11/2026), o Claude Haiku 5.5 com a camada de contexto respondeu "ROAS 0,60". Agora a regra está no dado: ROAS e CAC de campanhas de awareness voltam como **"não se aplica"**, com o motivo e com um status próprio (diferente de NULL, que segue significando "desconhecido"). O item 2 da política foi ampliado para ROAS e CAC; o PR desta mudança é a aprovação exigida pelo item 7.
5. **SLA de frescor global esconde problema.** O frescor é medido **por feed** (`freshnessPartitionBy: source`, em `customProperties`): o ga4 está fresco, e o meta_capi está 75h atrasado.

## 5. Lacunas conceituais preenchidas

- **Classes de reversibilidade concretas:** R0 leitura · R1 reversível (ajuste de orçamento com rollback) · R2 reversível com custo (pausar perde o aprendizado da plataforma) · R3 irreversível (nunca exposto ao agente).
- **Aprovação humana reavalia as pré-condições** no estado vivo. O estado pode ter mudado entre o pedido e a aprovação; o teste `test_approval_rechecks_live_state` cobre esse caso.
- **Log à prova de adulteração:** "conformidade" sem integridade do log não se sustenta numa auditoria. Cada span carrega o hash do anterior (`agentready verify`).
- **Modelo de Domínio com regras de negócio:** "receita é líquida", "awareness não usa ROAS" e "dado atrasado não é zero". Sem elas, a camada semântica seria só um dicionário de métricas.

## 6. Formato e logística

- O "repositório com branches por bloco" virou **um repositório com um comando por bloco** (`agentready demo 0..5`). O estado de cada bloco alimenta o seguinte, e `agentready setup` reinicia tudo em menos de 1s. Branches com pontos de partida de exercícios podem ser criadas depois, a partir desta versão completa.
- Agenda refeita para caber em 8h com intervalos (ver `01-roteiro-do-instrutor.md`). A regra de 30% teoria / 70% prática foi mantida nos blocos 1 a 5.
- Correção de texto: "Dinâmica de Gameficada" → "Dinâmica gamificada".

## 7. Limitações conhecidas (diga isso ao público)

- Os dados são sintéticos e determinísticos (seed 42), ancorados no horário de geração. Rode `agentready setup` no dia.
- O validador implementa um **subconjunto** do ODCS v3.1 (tipos, required, unique, mínimos, domínio via `invalidValues`, SLA de latência e taxa de quarentena).
- **Correção (2026-11-24):** a primeira versão dos contratos declarava ODCS v3.0.2, mas usava o tipo `timestamp` (só existe a partir da v3.1), a regra `rule: validValues` (não é uma forma do ODCS) e `partitionBy` dentro do SLA (campo não permitido). O `datacontract lint` da trilha stack apontou os três problemas. Os contratos foram migrados para ODCS v3.1.0 (`metric: invalidValues` e `customProperties.freshnessPartitionBy`), com versão menor incrementada; o validador do workshop aceita as duas formas.
- A interpretação de linguagem natural no Bloco 2 é por sinônimos. Em produção, um LLM faria essa etapa, mas **só escolhendo nomes de métricas**: quem gera o SQL continua sendo o compilador.
- A "plataforma de anúncios" é a tabela `ops.campaigns`.

## Fontes verificadas

- AtScale (ago/2024), press release e cobertura: [BusinessWire](https://www.businesswire.com/news/home/20240808651958/en/AtScale-Unveils-Breakthrough-in-Natural-Language-Processing-with-Semantic-Layer-and-Generative-AI) · [BigDataWire](https://bigdatawire.com/2024/08/15/atscale-claims-text-to-sql-breakthrough-with-semantic-layer)
- Precisely/Drexel LeBow, *2026 State of Data Integrity and AI Readiness*: [press release](https://www.precisely.com/press-release/fourth-annual-study-finds-ai-confidence-outpaces-readiness-as-data-integrity-gaps-persist/) · [relatório](https://www.precisely.com/resource-center/analyst-reports/2026-state-of-data-integrity-and-ai-readiness/)
- EU AI Act, art. 19: [AI Act Service Desk](https://ai-act-service-desk.ec.europa.eu/en/ai-act/article-19) · [artificialintelligenceact.eu](https://artificialintelligenceact.eu/article/19/) · obrigações do deployer (art. 26): [IAPP](https://iapp.org/news/a/eu-ai-act-deployer-evidence-gaps-smes-will-miss-before-2-aug-2026)
