# Trilha stack — o mesmo dia da Aurora, com ferramentas de produção

A trilha padrão do workshop roda tudo em Python escrito à mão, sem Docker, para que cada conceito fique visível. **Esta trilha roda o mesmo cenário com as ferramentas open source que times de dados usam em produção**: Airflow, dbt, Data Contract CLI e aprovação humana dentro do orquestrador (Fase 1); observabilidade de dados com Elementary e linhagem OpenLineage no Marquez (Fase 2).

A mensagem do workshop continua a mesma: **a lógica de decisão do agente não muda; muda a arquitetura ao redor dele.** Aqui ela ganha uma segunda parte: *"…e é assim que se roda isso em produção."* O comando `make parity` prova as duas ao vivo.

> **O que esta trilha NÃO é:** um substituto da demo do workshop (ela é opcional e mais pesada) nem um ambiente de produção (usuários e segredos fixos, só para estudo local).

## Pré-requisitos

- Docker Engine com os plugins **Compose ≥ 2.14** e **Buildx** (no Ubuntu: `sudo apt install docker-compose-v2 docker-buildx`)
- **≥ 4 CPUs** e **≥ 8 GB de RAM livre** (o `make up` confere e avisa). Pico medido numa execução completa da Fase 2: **2,6 GB** somando todos os containers
- Internet só na primeira vez (baixar imagens e pacotes); depois roda offline

## Início rápido

```bash
cd stack
make up                                   # constrói a imagem, sobe tudo e espera ficar saudável
make run ARGS='{"reset_scenario": true}'  # gera o cenário da manhã e roda o dia inteiro
make observe                              # os 4 pilares de dados da última execução (Fase 2)
make parity                               # prova: as duas trilhas decidem igual (7 cenários)
make test                                 # testes da trilha stack (dois ambientes Python)
make test-live                            # linhagem ao vivo, inclusive com o Marquez fora do ar (Fase 2)
make down                                 # para (mantém os dados)   ·   make reset: apaga os dados da trilha
```

| Interface | Endereço | Para quê |
|---|---|---|
| Airflow | **http://localhost:8080** | DAG, execuções, aprovações (**Required Actions**) |
| Linhagem (Marquez) | **http://localhost:3000** | grafo de linhagem emitido pelo próprio pipeline, com o histórico de cada execução (namespace `aurora`) |
| Relatório de observabilidade (Elementary) | **http://localhost:8090** | resultado e histórico de cada teste: contratos e os 4 pilares |

| Usuário | Senha | Papel |
|---|---|---|
| `instrutor` | `instrutor` | administrador: dispara execuções e acompanha |
| `aprovadora` | `aprovadora` | **única** pessoa que pode aprovar ou rejeitar ações do agente |

> ⚠️ Usuários e senhas fixos (`config/passwords.json`, fora do git) servem **apenas para estudo local**. Não exponha esta stack em rede.

Na primeira subida, o Airflow já dispara a execução agendada mais recente; como a Bronze está vazia, ela gera o cenário sozinha.

## O dia em um DAG: `aurora_midia_diario`

```
 ingestao ──▶ contratos ─────────────────────────────▶ gold ──▶ observabilidade ─────────▶ agente ──▶ aprovacao ──▶ fechamento
              │ lint (datacontract lint + gera testes)  dbt     │ verificar (4 pilares      o MESMO   HITL na       marca d'água,
              │ verificar (dbt: quarentena, disjuntores,        │   em dbt: obs_*)          agente    interface     resumo e
              │            Silver + testes do contrato)         ├ testes   (folha: vereditos) da trilha do Airflow  linhagem
              └ alerta_qualidade (folha: só problemas NOVOS)    ├ resumo   (folha: tabela)    padrão
                                                                └ relatorio (Elementary, :8090)
```

As folhas (`alerta_qualidade`, `testes`, `resumo`, `relatorio`) ficam vermelhas para chamar atenção, mas **nunca seguram o agente**: um pilar com falha é informação, não bloqueio. Quem bloqueia dado ruim são os disjuntores, no estágio de contrato. Se um modelo da observabilidade nem roda, o agente não roda (falha segura).

Parâmetros da execução (formulário "Trigger" no Airflow ou `make run ARGS='{...}'`):

| Parâmetro | Padrão | O que faz |
|---|---|---|
| `reset_scenario` | `false` | gera o cenário do zero (reset completo da trilha stack) |
| `backfill_meta` | `false` | chegam os lotes atrasados da Meta (o feed volta a ficar fresco) |
| `incident` | `nenhum` | injeta um incidente do Bloco 5: `centavos`, `renomeacao`, `lote_duplicado`, `feed_parado`, `aleatorio` |
| `autonomy_override` | `manter` | escada de autonomia global: `shadow`, `supervised`, `guarded`, `full`, `limpar` |
| `brain` | `rules` | `claude` usa o Claude (precisa de `ANTHROPIC_API_KEY` em `stack/.env`) |
| `gullible` | `false` | Bloco 3: o agente "acredita" no briefing com injeção de prompt |
| `disjuntor_distribuicao` | `compartilhado` | Bloco 5 (Fase 2): `ligado` / `desligado` **só nesta execução**; `compartilhado` lê `config/guardrails.yaml` → `observability.block_on_distribution_anomaly` (desligado de fábrica). A próxima execução sem o parâmetro volta para o compartilhado |

### Aprovar ou rejeitar uma ação

1. Quando o agente propõe algo acima do seu nível de autonomia (ex.: cortar 20% do orçamento), a execução **para** em `aprovacao.revisar`.
2. Entre como **`aprovadora`** e abra **Required Actions**. O formulário mostra campanha, valor atual → proposto, justificativa, por que precisa de você e a tabela de pré-condições.
3. **Aprovar**: as pré-condições são verificadas **de novo** no estado vivo e a mudança é registrada como `agent+aprovadora` (reversível com `make rollback CHG=...`). **Rejeitar**: nada muda.
4. **Sem resposta em 20h** (`config/stack.yaml`): o pedido **expira** como não aprovado e nada é executado. As 20h fazem o pedido expirar antes da execução do dia seguinte; como só roda uma execução por vez, uma aprovação pendente segura a próxima.

`make approvals` lista os pedidos pendentes no terminal; `make rollback CHG=CHG-xxxx` desfaz uma alteração aplicada.

### Idempotência e retentativa segura

- Rodar de novo com os **mesmos dados e os mesmos ajustes** não decide de novo: o agente registra *"já decidido para estes dados"* e nenhum orçamento muda.
- Se uma execução cair **depois** de aplicar mudanças, a retentativa **não** reaplica: ela para, lista o que foi feito e espera uma pessoa revisar.

### Alerta de qualidade

`contratos.alerta_qualidade` fica **vermelho só quando aparece lote barrado NOVO** desde a última execução bem-sucedida. O lote antigo com bug, barrado para sempre, não acende o alerta todo dia. O alerta é uma folha: Gold e agente seguem com o último dado bom, e a execução fica marcada como "precisa de atenção".

## Paridade: a prova de que o agente não mudou

```bash
make parity                    # os sete cenários   ·   make parity SCENARIO=manha
```

Cada trilha roda num processo isolado, com o mesmo cenário, o mesmo horário de referência e no mesmo dia: a padrão com `pipeline.run()` (Python à mão), a stack com `dbt build`. Depois, **o mesmo agente** decide nas duas. O comando compara a Gold campanha×dia (ao centavo), a saúde das fontes, cada decisão do agente e (Fase 2) o **veredito de cada pilar de observabilidade por alvo**, e termina com código 0 só se tudo for igual. Único mapeamento permitido: o aviso `histórico insuficiente` da stack vale como o "ok" da trilha padrão.

| Cenário | O que testa |
|---|---|
| `manha` | o cenário plantado: Meta parada, lote duplicado, sujeira, lote com bug |
| `pos_backfill` | depois que os lotes atrasados da Meta chegam |
| `supervisionado` | toda ação vira pedido de aprovação |
| `incidente_centavos` | lote de ontem do ga4 reenviado em centavos: o contrato aprova, o pilar **distribuição** falha nas duas trilhas |
| `incidente_renomeacao` | `campaign_id` renomeado: pilar **esquema** (e o frescor do ga4) |
| `incidente_lote_duplicado` | lote reenviado sem idempotência: pilar **volume** |
| `incidente_feed_parado` | o lote de ontem nunca chegou: pilares **frescor** e **volume** |

## Mapa de substituição: cada ferramenta substitui um módulo

Regra da trilha (constituição, Princípio VI): **ferramenta que não substitui um módulo da trilha padrão não entra.**

| Ferramenta (Fase 1) | Versão | Substitui (trilha padrão) | Bloco |
|---|---|---|---|
| **Apache Airflow** (DAG, pool, agenda) | 3.3.2 | a ordem das etapas em `pipeline.run()` e os comandos `setup` / `pipeline` / `backfill-meta` / `incident inject` (agora parâmetros do DAG) | 1, 5 |
| **Airflow Human-in-the-loop** | provider padrão | `agentready approvals` / `approve` / `reject` (a fila de aprovação na CLI) | 4 |
| **dbt-core + dbt-duckdb** | 1.12.7 · 1.11.1 | a materialização de `contracts.apply()` (Silver, Quarentena, `batch_status`), `pipeline.build_gold()` e `pipeline.write_health()` | 1, 2 |
| **astronomer-cosmos** | 1.16.0 | a "cola" em Python que rodava as etapas em sequência: cada modelo e teste dbt vira uma tarefa visível no Airflow | 1 |
| **Data Contract CLI** | 1.2.11 | a leitura dos tipos do contrato para checar a Silver: gera os testes dbt a partir do ODCS, e acrescenta o `lint` dos contratos (um portão novo) | 1 |

| Ferramenta (Fase 2) | Versão | Substitui (trilha padrão) | Bloco |
|---|---|---|---|
| **Elementary** (pacote dbt + `edr report`) | 0.26.1 | `observability.report()` e `agentready observe`: rodar as checagens dentro do pipeline, guardar cada resultado por execução (histórico) e mostrar o relatório | 5 |
| **Modelos dbt `obs_*` + disjuntor de distribuição no estágio de contrato** | — | `observability.freshness/volume/distribution/schema()` e `block_anomalous_batches()` | 5 |
| **OpenLineage** (provider do Airflow + Cosmos) | 2.20.1 · 1.53.0 | `observability.LINEAGE` / `downstream()`: linhagem emitida pelo que de fato rodou | 4, 5 |
| **Marquez** | 0.50.0 | `agentready lineage` (a árvore no terminal) → grafo navegável com o histórico de execuções | 4, 5 |
| *(consulta nova)* `make decisoes` | — | `observability.decisions_since()` | 5 |

**Substituição parcial, com honestidade:**

- **O Elementary roda as NOSSAS regras, não as estatísticas dele.** As faixas de mediana do Bloco 5 (volume 0,5x–1,5x, distribuição 0,5x–2x) viraram modelos dbt `obs_*`; as detecções estatísticas do próprio Elementary (z-score sobre janelas de treino) marcariam outros lotes e quebrariam a paridade. O Elementary substitui o que o `observability.py` fazia *em volta* da regra: executar, guardar o histórico e mostrar.
- **O Marquez não mostra os nós da camada semântica e do MCP** (`métrica *`, `tool *`, `guarda de frescor`, `pré-condição dados_frescos`): nenhuma etapa do pipeline os produz. Desenhá-los à mão seria a linhagem "desenhada" que a Fase 2 substituiu; o `agentready lineage` da trilha padrão continua mostrando esses nós.

- **`contracts.violation_exprs()` continua compartilhado.** Nenhuma ferramenta open source faz quarentena **linha a linha** com **disjuntor por lote**: Data Contract CLI, Soda e Great Expectations testam o conjunto de dados inteiro. Então as regras ODCS continuam virando SQL num único lugar, chamado de dentro do dbt. O mesmo vale para `pipeline.freshness()` (a regra de frescor), para a paridade ser exata.
- **Postgres não substitui módulo nenhum:** é o banco de metadados exigido pelo próprio Airflow, parte do orquestrador.

**Achado real:** o `datacontract lint` desta trilha mostrou que os contratos originais **não eram ODCS válido** (declaravam v3.0.2 mas usavam o tipo `timestamp`, a regra `rule: validValues` e `partitionBy` dentro do SLA). Eles foram migrados para **ODCS v3.1.0**; veja a nota em [`docs/00-validacao-do-projeto.md`](../docs/00-validacao-do-projeto.md).

## Lacunas conhecidas (diga isso ao público)

- **O `centavos` continua passando nos contratos — de propósito.** Agora quem pega é o pilar de **distribuição** (Fase 2); o contrato continua aprovando o lote, porque é essa a lição do Bloco 5: contrato ≠ observabilidade. Com o disjuntor de distribuição desligado (padrão), o agente ainda decide sobre o dado em centavos: é um incidente.
- **Traces e painéis** continuam como na trilha padrão (`agentready trace`) até a Fase 3.
- **Marquez: projeto ativo; última versão publicada 0.50.0 (out/2024).** O trabalho mais novo está na `main`, sem versão publicada; usamos a última versão oficial. O README do Marquez pede PostgreSQL 14; aqui ele roda no Postgres 16 da stack (as 91 migrações aplicaram sem erro). A busca do Marquez (OpenSearch) fica desligada: não é usada.
- **O feed ga4 aparece na linhagem como `bronze.conversions`** (sem nó por fonte até a Fase 4, quando a ingestão passa a ser de verdade).
- **Histórico curto vira aviso, não veredito.** Com menos de 7 pontos na linha de base (`config/stack.yaml`), volume e distribuição mostram `histórico insuficiente` e nunca bloqueiam. A trilha padrão diz "ok" nesse caso; a paridade trata os dois como iguais. Se o histórico for curto **e** a razão sair da faixa, a padrão falha e a stack avisa — a paridade mostra essa diferença.
- **Falha de pilar aparece como erro no relatório**, mas os testes de veredito ficam fora do `dbt build` sem `--select` (`dbt/aurora/selectors.yml`): na manhã do cenário a Meta está parada de propósito, e isso não pode derrubar o build das camadas.
- **O servidor MCP e a camada semântica** não mudaram: o agente desta trilha usa as mesmas capacidades dentro do processo.
- **Depois de mudar um contrato**, o Cosmos só mostra as tarefas de teste novas quando o DAG é lido de novo (alguns segundos; ou reinicie o `airflow-dag-processor`).

## Roteiro das próximas fases

Cada fase troca mais um módulo escrito à mão por uma ferramenta de produção, e deixa o cenário mais realista.

| Fase | Ferramenta | Substitui | Bloco | Fica mais realista |
|---|---|---|---|---|
| **2** ✅ | **OpenLineage + Marquez** | o comando `lineage` | 4, 5 | **feito:** linhagem emitida pelo próprio pipeline, até a decisão do agente (com o `trace_id`) |
| **2** ✅ | **Elementary** (observabilidade de dados no dbt) | `observability.py` | 5 | **feito:** os 4 pilares no pipeline, com histórico; **pega o `centavos`** que passa no contrato |
| **3** | **OpenTelemetry Collector + Phoenix ou Langfuse + Grafana** | `tracing.py` e o log JSONL com cadeia de hash | 4 | traces de pipeline e de agente num só lugar, com painéis |
| **4** | **APIs simuladas (FastAPI) + dlt** | a carga estática de `generate.py` | 1 | lotes atrasados, duplicados e quebrados chegando como na vida real |
| **4** | **Open Policy Agent (OPA)** | a aplicação de `config/guardrails.yaml` | 3 | guardrails como política versionada e testável, fora do agente |
| **4** | **DuckLake ou Iceberg em MinIO** | o arquivo único do warehouse | 5 | snapshots: rollback do incidente vira *time travel* de verdade |
| **5** *(opcional)* | **OpenMetadata ou DataHub** | — (catálogo) | 1, 2 | glossário, donos e contratos num só lugar |

## Bloco 5 na trilha stack (Fase 2)

Mesmo roteiro do Bloco 5 da trilha padrão, com as ferramentas da stack. TTD e TTR saem do mesmo registro de incidente.

1. **Injetar** (sem dizer qual): `make run ARGS='{"incident": "aleatorio"}'`.
2. **Detectar**: no Airflow, a folha **`observabilidade.resumo`** fica vermelha; o log dela tem a tabela dos 4 pilares (ou `make observe`). O histórico de cada pilar está no relatório (**:8090**). Registre a detecção: `make incidente ACAO=detectar`.
3. **Rastrear o impacto**: no Marquez (**:3000**, namespace `aurora`), parta de `bronze.conversions` (onde o feed ga4 chega) até `aurora_midia_diario.agente.executar`; a execução do agente traz o `trace_id`. As decisões candidatas a rollback: `make decisoes DESDE=<horário da injeção>` (o horário aparece em `make incidente ACAO=listar`).
4. **Conter**: `make rollback CHG=CHG-xxxx` para cada alteração executada depois do incidente.
5. **Resolver**: `make incidente ACAO=resolver` — restaura a Bronze, mostra **TTD/TTR** e dispara uma execução para reconstruir as camadas. `make incidente ACAO=revelar` mostra qual era o incidente.
6. **Ação corretiva do post-mortem** (centavos): ligar o disjuntor de distribuição. No palco, sem editar arquivo compartilhado: `make run ARGS='{"incident": "centavos", "disjuntor_distribuicao": "ligado"}'` — o lote em centavos vai para a quarentena (`anomalia de distribuição: ticket médio fora da banda`), fica barrado e não chega à Gold nem ao agente; o alerta de qualidade acusa o lote novo barrado. Para tornar permanente: `config/guardrails.yaml` → `observability.block_on_distribution_anomaly: true` (vale para as duas trilhas).

| Incidente | Pilar que falha (nas duas trilhas) |
|---|---|
| `centavos` | distribuição (`conversions/ga4.order_value_brl`) |
| `renomeacao` | esquema (`bronze.conversions`) e frescor do ga4 |
| `lote_duplicado` | volume (`conversions/ga4`) |
| `feed_parado` | frescor e volume do ga4 |

## Tempos medidos (checkout limpo, 2026-11-24)

Máquina: 20 CPUs, 31 GB de RAM; imagens base já baixadas (o SC-001 exclui downloads).

| Etapa | Tempo | Meta |
|---|---|---|
| build da imagem sem cache (`uv` instala os 3 ambientes) | 21 s | — |
| `make up` até tudo saudável | 32 s | |
| primeira execução completa, até parar na aprovação | ~70 s | ≤ 5 min por execução |
| reexecução idêntica (agente pulado) | 72 s | ≤ 5 min |
| `make parity` (3 cenários × 2 trilhas) | 21 s | — |
| do `make up` ao fim do roteiro V1–V8 (inclui `make test`) | 634 s (~10,5 min) | **SC-001: ≤ 15 min** até a primeira execução terminar (bem abaixo) |
| `aprovadora` acha, revisa e decide um pedido na UI (do login ao envio) | 55 s na primeira vez · 30 s com prática | **SC-006: < 1 min** |

O tempo de decisão foi medido com uma pessoa, com o cronômetro da tela de login até o envio do formulário em **Required actions**. Na primeira vez ele fica perto do limite: a maior parte vai na leitura da justificativa e da tabela de verificações, que é onde a atenção deve estar. A aplicação da decisão pelo Airflow (~15 s) não entra nessa conta.

### Fase 2 (checkout limpo da branch, 2026-11-25)

Mesma máquina. Clone novo da branch, sem nenhum dado local.

| Etapa | Tempo | Meta |
|---|---|---|
| build da imagem sem cache (agora com Elementary e os pacotes internos do `edr`) | 37 s | — |
| `make up` até tudo saudável (+ Marquez, relatório) | 48 s | |
| primeira execução (agendada), até parar na aprovação | 138 s | **SC-007: ≤ 5 min** |
| do clone até a primeira execução parar na aprovação | ~3,8 min | **SC-007: ≤ 15 min** |
| execução completa em modo shadow (sem aprovação) | 150–160 s | ≤ 5 min |
| mesma execução com o Marquez **parado** | 145–150 s | sem diferença (FR-013) |
| `make test` (71 + 13 testes) | ~10,5 min | — |
| `make parity` (7 cenários × 2 trilhas) | 116 s | — |
| `make test-live` (3 execuções em shadow) | ~8,3 min | — |
| pico de RAM numa execução (todos os containers) | 2,6 GB (agendador 1,4 GB · Marquez 0,5 GB) | mínimo documentado: 8 GB livres |

## Estrutura

```
stack/
├── compose.yaml, Dockerfile     Airflow 3.3 + Postgres; imagem com 3 venvs isolados (dbt, datacontract-cli, agente)
├── compose.yaml (Fase 2)        + marquez-api, marquez-web, relatorio, marquez-db-init (banco "marquez" no mesmo Postgres)
├── Makefile                     up · run · approvals · rollback · parity · test · down · reset · contracts-sync
│                                + observe · incidente · decisoes · test-live (Fase 2)
├── config/stack.yaml            agenda, tempo de aprovação, aprovadores, faixas e histórico mínimo da observabilidade
├── config/edr/config.yml        edr sem `dbt deps` (offline) e sem telemetria
├── dags/aurora_midia_diario.py  o único DAG  ·  dags/_lineage_facets.py: trace_id do agente na linhagem
├── dbt/aurora/                  contrato (registro, quarentena, disjuntores) → Silver → Gold → observabilidade (obs_*)
├── agentready_stack/            tarefas do DAG, livro-razão, aprovações, paridade, observabilidade, incidentes, linhagem
├── scripts/                     contracts-sync.sh (lint + testes gerados + Elementary) · lineage_live_check.py
└── tests/                       um teste por promessa (Fases 1 e 2)
```

O código do agente, os contratos, a configuração e o corpus **não são copiados**: a raiz do repositório é montada somente leitura em `/opt/agentready`. Mudou na trilha padrão, mudou aqui.

## Problemas comuns

| Sintoma | Causa e solução |
|---|---|
| `docker: unknown command: docker compose` | falta o plugin Compose v2: `sudo apt install docker-compose-v2 docker-buildx` |
| execução nova fica "queued" | só roda uma execução por vez: há uma aprovação esperando em **Required Actions** |
| relatório em :8090 diz "ainda não gerado" | nenhuma execução terminou a etapa `observabilidade.relatorio`; se ela avisou `relatório de observabilidade não atualizado`, veja o log dela (o resto da execução não é afetado) |
| tarefas de teste do contrato sumiram (`campaigns_run` em vez de `campaigns.run` + `campaigns.test`) | o Cosmos guardou em cache um `dbt ls` antigo. Limpe o cache: `docker compose exec airflow-scheduler airflow variables delete cosmos_cache__aurora_midia_diario__contratos__verificar` (o DAG é relido em ~1 min). Desde a Fase 2 os testes gerados são trocados de forma atômica, o que evita o problema |
| Marquez vazio em :3000 | escolha o namespace **`aurora`** no canto superior; os eventos chegam ao fim de cada tarefa |
| `o warehouse DuckDB está aberto por outro processo` | um escritor por vez: espere a execução atual terminar |
| arquivos em `stack/` com dono errado | rode via `make` (ele cria `stack/.env` com o seu UID) |

Especificação, plano e decisões: [`specs/001-stack-production-track/`](../specs/001-stack-production-track/) (Fase 1) e [`specs/002-stack-lineage-observability/`](../specs/002-stack-lineage-observability/) (Fase 2).
