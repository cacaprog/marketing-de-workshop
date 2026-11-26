# Trilha stack — o mesmo dia da Aurora, com ferramentas de produção

A trilha padrão do workshop roda tudo em Python escrito à mão, sem Docker, para que cada conceito fique visível. **Esta trilha roda o mesmo cenário com as ferramentas open source que times de dados usam em produção**: Airflow, dbt, Data Contract CLI e aprovação humana dentro do orquestrador (Fase 1); observabilidade de dados com Elementary e linhagem OpenLineage no Marquez (Fase 2); traces do pipeline e do agente num só lugar, com OpenTelemetry e Arize Phoenix (Fase 3); fontes que falham de verdade, carregadas pelo dlt, guardrails como política no Open Policy Agent e snapshots com *time travel* no DuckLake (Fase 4).

A mensagem do workshop continua a mesma: **a lógica de decisão do agente não muda; muda a arquitetura ao redor dele.** Aqui ela ganha uma segunda parte: *"…e é assim que se roda isso em produção."* O comando `make parity` prova as duas ao vivo.

> **O que esta trilha NÃO é:** um substituto da demo do workshop (ela é opcional e mais pesada) nem um ambiente de produção (usuários e segredos fixos, só para estudo local).

## Pré-requisitos

- Docker Engine com os plugins **Compose ≥ 2.14** e **Buildx** (no Ubuntu: `sudo apt install docker-compose-v2 docker-buildx`)
- **≥ 4 CPUs** e **≥ 8 GB de RAM livre** (o `make up` confere e avisa). Pico medido numa execução completa: **2,6 GB** na Fase 2; **3,0 GB** com a Fase 3 (Phoenix 0,4 GB · coletor 0,1 GB incluídos); **3,4 GB** com a Fase 4 (fontes simuladas e OPA incluídos), somando todos os containers. Disco do lake: ~1–2 MB por execução (35 MB num dia com ~30 execuções), até o `make reset`
- Internet só na primeira vez (baixar imagens e pacotes); depois roda offline

## Início rápido

```bash
cd stack
make up                                   # constrói a imagem, sobe tudo e espera ficar saudável
make run ARGS='{"reset_scenario": true}'  # gera o cenário da manhã e roda o dia inteiro
make observe                              # os 4 pilares de dados da última execução (Fase 2)
make parity                               # prova: as duas trilhas decidem igual (7 cenários)
make test                                 # testes da trilha stack (dois ambientes Python)
make traces                               # últimas execuções com o link do trace no Phoenix (Fase 3)
make auditoria                            # confere a cadeia de hash do log de auditoria (Fase 3)
make fontes                               # a última carga de cada fonte simulada (Fase 4)
make snapshots                            # marcos do lake: o que cada etapa de cada execução gravou (Fase 4)
make politica ACAO='ajustar C01 5200'     # a política permitiria esta ação? (Fase 4; não executa nada)
make test-live                            # linhagem e traces ao vivo, com Marquez, Phoenix e coletor fora do ar (~30 min)
make down                                 # para (mantém os dados)   ·   make reset: apaga os dados da trilha
```

| Interface | Endereço | Para quê |
|---|---|---|
| Airflow | **http://localhost:8080** | DAG, execuções, aprovações (**Required Actions**) |
| Linhagem (Marquez) | **http://localhost:3000** | grafo de linhagem emitido pelo próprio pipeline, com o histórico de cada execução (namespace `aurora`) |
| Relatório de observabilidade (Elementary) | **http://localhost:8090** | resultado e histórico de cada teste: contratos e os 4 pilares |
| Traces (Arize Phoenix) | **http://localhost:6006** | um trace por execução: cada tarefa do pipeline e, dentro dele, a árvore de decisão do agente (projeto `aurora`) |
| Fontes simuladas (APIs) | **http://localhost:8000/docs** | as quatro fontes da Aurora (investimento, GA4, Meta, catálogo) que a ingestão consulta — só em `127.0.0.1`; a administração delas fica na rede interna |

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
| `falhas_upstream` | `padrao` | Fase 4: falhas roteirizadas das fontes nesta execução. `padrao` derruba a página 2 do ga4 uma vez (a nova tentativa aparece no log); `todas`, a 1ª tentativa de toda página; `nenhuma` |
| `fonte_fora_do_ar` | `nenhuma` | Fase 4: `ads`, `ga4`, `meta_capi` ou `catalogo` responde 503 a execução inteira: a carga dela é registrada como `falhou`, as outras seguem e o frescor dela vence sozinho |
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

Cada trilha roda num processo isolado, com o mesmo cenário, o mesmo horário de referência e no mesmo dia: a padrão com `pipeline.run()` (Python à mão), a stack com `dbt build`. Depois, **o mesmo agente** decide nas duas. O comando compara a Gold campanha×dia (ao centavo), a saúde das fontes, cada decisão do agente (Fase 2) o **veredito de cada pilar de observabilidade por alvo**, (Fase 3) o trace do agente e (Fase 4) a **Bronze por lote** — na stack ela chega pelas fontes simuladas e pelo dlt —, o **status de cada carga** e a **política** (cada checagem de cada ação, e os casos de `stack/policy/testes/casos.yaml` pelo Python e pelo OPA), e termina com código 0 só se tudo for igual. Único mapeamento permitido: o aviso `histórico insuficiente` da stack vale como o "ok" da trilha padrão.

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

| Ferramenta (Fase 3) | Versão | Substitui (trilha padrão) | Bloco |
|---|---|---|---|
| **Traces nativos do Airflow** (OpenTelemetry) | 3.3.2 | — (recurso do orquestrador que já está na stack): um span por execução e por tarefa, para o pipeline entrar no mesmo trace do agente | 4, 5 |
| **OpenTelemetry Collector** | 0.166.0 | o ponto de saída do `tracing.py` (um arquivo, ou um único endereço): recebe os spans do Airflow, das tarefas da stack e do agente, marca o projeto e o tipo de span e **guarda em disco enquanto o Phoenix está fora do ar** | 4 |
| **Arize Phoenix** | 22.0.1 | `agentready trace` (a lista e a árvore no terminal) e `tracing.render_html()`: busca, árvore de spans, atributos e erros no navegador, com link a partir da aprovação | 4, 5 |
| *(comando novo)* `make traces` | — | `agentready trace` sem argumento (a lista de traces) | 4, 5 |

**Substituição parcial, com honestidade:**

- **O Elementary roda as NOSSAS regras, não as estatísticas dele.** As faixas de mediana do Bloco 5 (volume 0,5x–1,5x, distribuição 0,5x–2x) viraram modelos dbt `obs_*`; as detecções estatísticas do próprio Elementary (z-score sobre janelas de treino) marcariam outros lotes e quebrariam a paridade. O Elementary substitui o que o `observability.py` fazia *em volta* da regra: executar, guardar o histórico e mostrar.
- **O Marquez não mostra os nós da camada semântica e do MCP** (`métrica *`, `tool *`, `guarda de frescor`, `pré-condição dados_frescos`): nenhuma etapa do pipeline os produz. Desenhá-los à mão seria a linhagem "desenhada" que a Fase 2 substituiu; o `agentready lineage` da trilha padrão continua mostrando esses nós.

- **`contracts.violation_exprs()` continua compartilhado.** Nenhuma ferramenta open source faz quarentena **linha a linha** com **disjuntor por lote**: Data Contract CLI, Soda e Great Expectations testam o conjunto de dados inteiro. Então as regras ODCS continuam virando SQL num único lugar, chamado de dentro do dbt. O mesmo vale para `pipeline.freshness()` (a regra de frescor), para a paridade ser exata.
- **Postgres não substitui módulo nenhum:** é o banco de metadados exigido pelo próprio Airflow, parte do orquestrador. Marquez e Phoenix usam bancos próprios nele.
- **A cadeia de hash continua sendo o registro de auditoria (Fase 3).** O `HashChainJsonlExporter` e o `verify_chain()` do `tracing.py` **não** foram substituídos: o agente continua gravando `data/traces/audit.jsonl` do jeito de sempre, e o Phoenix recebe uma **cópia** pelo coletor. O Phoenix é para explorar; ele **não é à prova de adulteração** (é um banco que qualquer pessoa com acesso edita). A prova é `make auditoria`.
- **O `tracing.py` não mudou uma linha.** Ele já sabia exportar por OTLP quando `OTEL_EXPORTER_OTLP_ENDPOINT` está definido; a stack só define a variável e passa o contexto da tarefa do Airflow (`TRACEPARENT`), e os spans do agente nascem dentro do trace da execução.

**Achado real:** o `datacontract lint` desta trilha mostrou que os contratos originais **não eram ODCS válido** (declaravam v3.0.2 mas usavam o tipo `timestamp`, a regra `rule: validValues` e `partitionBy` dentro do SLA). Eles foram migrados para **ODCS v3.1.0**; veja a nota em [`docs/00-validacao-do-projeto.md`](../docs/00-validacao-do-projeto.md).

| Ferramenta (Fase 4) | Versão | Substitui (trilha padrão) | Bloco |
|---|---|---|---|
| **Fontes simuladas (FastAPI)** — serviço `upstream` | FastAPI 0.165 | a escrita da Bronze pelo `generate.py` (`generate()`, `backfill_meta()`) e pelo `incidents.inject/resolve` na stack: o gerador compartilhado agora escreve as **fontes**, e incidentes acontecem nelas | 1, 5 |
| **dlt** (fonte REST API declarativa) | 1.32.0 | a carga estática do cenário: uma carga por fonte, com paginação, novas tentativas, detecção de mudança e registro (`make fontes`) | 1 |
| **DuckLake** (catálogo no Postgres, arquivos em `data/lake/`) | spec 1.1 · DuckDB 2.0.1 | o arquivo único do warehouse **para as camadas de dados** e o backup feito à mão do incidente (`meta.incident_backup`): snapshots, *time travel* e restauração. *Parcial:* o estado operacional (orçamentos, change log, aprovações) fica no `ops.duckdb`, fora dos snapshots — de propósito | 5 |
| **Open Policy Agent** | 1.22.4 | a aplicação de `config/guardrails.yaml` em `capabilities.py` (na stack, quem decide é o OPA); os limites continuam no YAML compartilhado | 3 |

## Lacunas conhecidas (diga isso ao público)

- **O `centavos` continua passando nos contratos — de propósito.** Agora quem pega é o pilar de **distribuição** (Fase 2); o contrato continua aprovando o lote, porque é essa a lição do Bloco 5: contrato ≠ observabilidade. Com o disjuntor de distribuição desligado (padrão), o agente ainda decide sobre o dado em centavos: é um incidente.
- **A cópia do trace no Phoenix não é à prova de adulteração** (Fase 3). Explore no Phoenix, prove com a cadeia de hash: `make auditoria`.
- **Sem spans dentro do dbt.** O dbt não emite OpenTelemetry; cada modelo e teste aparece como uma tarefa do Airflow (`task_run.*` → `worker.*`), com duração e status, mas sem o SQL por dentro.
- **O span raiz da execução chega no fim dela** (o Airflow o emite quando a execução termina, depois da espera por aprovação). Até lá, a execução não aparece na aba *Traces* do Phoenix; use o link do log de `agente.executar` (ou `make traces`) ou a aba *Spans*.
- **Tarefa que nem começou não vira span** (porque um passo anterior falhou): o span raiz termina em erro e o Airflow mostra as tarefas que não rodaram.
- **Phoenix 22 é uma versão nova** (nov/2026). A autenticação vem ligada quando ele escuta fora do loopback; aqui ela é desligada de propósito (`PHOENIX_ENABLE_AUTH=false`), como nas outras interfaces de estudo local.
- **`agentready trace` sem argumento não lista as execuções da stack.** Desde a Fase 3 o `agent.run` é filho da tarefa do Airflow, e essa lista só mostra spans sem pai. Para a lista, use `make traces`. Com o id (`agentready trace <trace_id>`, dentro do container), a árvore do agente continua aparecendo no terminal, lida do log de auditoria — o plano B se o Phoenix estiver fora. A trilha padrão (`demo 4`) não muda.
- **Marquez: projeto ativo; última versão publicada 0.50.0 (out/2024).** O trabalho mais novo está na `main`, sem versão publicada; usamos a última versão oficial. O README do Marquez pede PostgreSQL 14; aqui ele roda no Postgres 16 da stack (as 91 migrações aplicaram sem erro). A busca do Marquez (OpenSearch) fica desligada: não é usada.
- **O estado operacional não está no lake** (substituição parcial do arquivo único, Fase 4): orçamentos, change log, aprovações e o livro-razão do agente ficam no `ops.duckdb`. De propósito: uma viagem no tempo nunca pode voltar uma decisão de dinheiro — o dado volta pelo lake; o orçamento, pelo `make rollback`.
- **Sincronização completa, não incremental** (Fase 4): cada fonte é comparada pelo manifesto de lotes e, se mudou, trocada inteira. As fontes deste cenário retiram e substituem lotes (`centavos`, `renomeacao`, `feed_parado`); com cursor incremental, o lote original e o em centavos ficariam juntos e o contrato barraria por chave duplicada — a lição do Bloco 5 sumiria. Em produção, cursor incremental é o padrão.
- **O dlt não grava no lake (ainda)**: o dlt 1.32 exige DuckDB < 2 nos destinos DuckDB/DuckLake. Ele grava Parquet e a stack faz o commit no DuckLake numa transação; quando o dlt suportar DuckDB 2, o destino `ducklake` dele substitui esse passo.
- **O dlt não emite linhagem própria**: os nós das fontes no Marquez vêm dos datasets declarados nas tarefas do DAG.
- **Snapshots não expiram sozinhos**: os arquivos crescem até o `make reset` (veja o disco por execução em "Tempos medidos").
- **As regras existem em duas formas** (Python na trilha padrão, Rego no OPA): o teste de equivalência e a paridade (seção `policy`) falham em qualquer diferença. A frase em pt-BR de cada checagem é montada em Python para as duas — o OPA decide, o texto é o mesmo.
- **DuckLake 1.1 é versão nova** (out/2026). O Marquez e as outras ferramentas não mostram os snapshots.
- **As fontes são uma simulação**: falhas determinísticas, sem autenticação, só os 503 roteirizados.
- **Um `meta.incident_backup` vazio fica no lake**: o código compartilhado de incidentes o cria; a stack não o usa (quem restaura é o snapshot).
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
| **3** ✅ | **OpenTelemetry Collector + Arize Phoenix** | a exportação e a visualização do `tracing.py` (a cadeia de hash fica) | 4 | **feito:** traces de pipeline e de agente num só lugar, com link da aprovação até o raciocínio do agente |
| **4** ✅ | **APIs simuladas (FastAPI) + dlt** | a carga estática de `generate.py` | 1 | **feito:** lotes atrasados, duplicados e quebrados chegando por HTTP, com falhas e novas tentativas; um nó por fonte na linhagem |
| **4** ✅ | **Open Policy Agent (OPA)** | a aplicação de `config/guardrails.yaml` | 3 | **feito:** guardrails como política versionada e testável, fora do agente; sem OPA, nenhuma escrita |
| **4** ✅ | **DuckLake** (catálogo no Postgres) | o arquivo único do warehouse (camadas de dados) | 5 | **feito:** snapshots com nome; resolver um incidente é voltar ao último estado limpo, e dá para desfazer |
| **5** *(opcional)* | **OpenMetadata ou DataHub** | — (catálogo) | 1, 2 | glossário, donos e contratos num só lugar |

**Por que não Iceberg nem MinIO (Fase 4):** Iceberg exigiria um serviço de catálogo REST e armazenamento de objetos (dois serviços a mais no limite de 8 GB); o DuckLake vem com o DuckDB 2.0 que a stack já usa e guarda o catálogo no Postgres que já existe. O MinIO entrou em modo de manutenção e deixou de publicar imagens da edição comunitária em 23/10/2025 (só código-fonte; [README do projeto](https://github.com/minio/minio)) — por isso os arquivos ficam num volume local.

**Grafana saiu do roteiro (Fase 3):** nenhum módulo da trilha padrão para ele substituir (Princípio VI); as visões do próprio Phoenix bastam para o Bloco 4. Ele volta se alguém propuser o módulo que ele substitui. **Langfuse** era a alternativa ao Phoenix; ficou de fora porque exige ClickHouse, Redis e armazenamento de objetos, o que põe em risco o mínimo de 8 GB.

## Blocos 1, 3 e 5 na trilha stack (Fase 4)

**Bloco 1 — o dado chega de fora.** Abra **http://localhost:8000/docs**: são as quatro fontes que a ingestão consulta. Rode `make run ARGS='{"reset_scenario": true, "autonomy_override": "shadow"}'` e mostre as tarefas `ingestao.ads`, `ingestao.ga4`, `ingestao.meta_capi` e `ingestao.catalogo`; depois `make fontes`: o ga4 mostra *"1 nova tentativa após erro da fonte"* (a página 2 caiu e o dlt tentou de novo). O lote duplicado do ga4 **chega** na Bronze — a ingestão não conserta nada — e quem o barra continua sendo o contrato. Para mostrar uma fonte fora do ar: `make run ARGS='{"fonte_fora_do_ar": "ga4", "autonomy_override": "shadow"}'` → a carga do ga4 fica `falhou`, as outras seguem e o frescor do ga4 vence sozinho (nunca vira zero).

**Bloco 3 — a política decide, não o agente.** `make politica ACAO='ajustar C01 5200'` → `NEGADO (variacao_maxima)`, com as mesmas frases que o trace do agente sempre teve; quem decidiu foi o OPA (`policy.evaluator=opa` no span da ação, no Phoenix). Para provar que a política é testável: copie `config/guardrails.yaml`, mude um limite na cópia e rode o teste de mutação (`make test`) — algum caso de `stack/policy/testes/casos.yaml` muda de veredito; `make politica-testes` mostra os casos. O agente "crédulo" (`"gullible": true`) pede R$ 35.000 para a C06 por causa do briefing e o OPA nega (`variacao_maxima`, `teto_do_portfolio`): texto não autoriza nada. Com o OPA parado (`docker compose stop opa`), o agente **não roda** (falha fechada) — nenhuma escrita sem política.

**Bloco 5 — resolver é voltar ao último estado limpo.**
1. `make run ARGS='{"autonomy_override": "shadow"}'` (execução limpa) → `make run ARGS='{"incident": "centavos", "autonomy_override": "shadow"}'`.
2. `make snapshots`: os marcos de cada execução (`ingestao.*`, `contratos`, `gold_observabilidade`, `agente`), com o incidente aberto marcado.
3. `make gold-em DECISAO=<trace_id>` (de `make traces`): a Gold **exatamente como o agente viu** ao decidir — com o ticket médio 100x.
4. `make incidente ACAO=resolver`: a fonte volta ao normal e o lake volta ao marco `agente` da execução limpa — **um comando**, com TTD/TTR. Gold e saúde das fontes ficam idênticas às da execução limpa; a restauração vira um snapshot novo e se desfaz com `make restaurar PARA=<de>`.
5. O dado volta pelo lake; **o dinheiro, pelo change log**: orçamentos alterados com o dado ruim se desfazem com `make rollback CHG=…`.

`make consultar-em TABELA=gold.campaign_daily EM=<snapshot>` lê qualquer tabela das camadas de dados num ponto do lake (o `ops` não viaja no tempo).

## Bloco 4 na trilha stack (Fase 3)

Mesmo roteiro do Bloco 4 da trilha padrão — o "interrogatório do auditor" —, agora no Phoenix (**:6006**).

1. **Rodar o dia**: `make run ARGS='{"reset_scenario": true}'`. No log da tarefa **`agente.executar`** aparece `Trace desta execução no Phoenix: http://localhost:6006/redirects/traces/<id>`; `make traces` lista as últimas execuções com o link.
2. **Abrir o trace**: o link abre a execução inteira — `dag_run.aurora_midia_diario` → uma tarefa por linha (`task_run.*` → `worker.*`) → dentro de `worker.agente.executar`, a árvore do agente: `agent.run` → `agent.reasoning`, `tool.*`, `resource.*`. Os spans do pipeline também estão lá: `contratos.lote` (um por lote; vermelho = barrado, com o motivo), `observabilidade.veredito` (um por pilar e alvo), `agente.resultado`, `fechamento.resumo`.
3. **As três perguntas do auditor** (exercício 1 do Bloco 4):
   - *Por que o orçamento do C01 subiu? Com base em qual número?* → `tool.adjust_campaign_budget` (C01): `justification`, `params.new_daily_budget_brl`, `preconditions` e `autonomy.level`; o número vem de `tool.get_campaign_performance` (`semantic.sql`).
   - *Qual versão do modelo semântico e dos guardrails valia?* → `tool.get_campaign_performance` (`semantic.model_version`) e `tool.get_data_health` (`data.contracts`).
   - *Por que nada foi feito com C03?* → `agent.reasoning` (`decisions`): recusa por dado parado da Meta, com a regra de frescor; `tool.get_data_health` mostra `data.stale_sources`.
4. **Da aprovação ao raciocínio**: com `ARGS='{"autonomy_override": "supervised"}'`, o pedido em **Required Actions** traz **"Abrir o raciocínio do agente no Phoenix"**. A decisão humana aparece no mesmo trace como **`humano.decisao`**, com o desfecho (`executed`, `rejected`, `rejected_live_recheck` ou `expired`), quem decidiu e o comentário; na aprovação, o `human.approval` do código compartilhado vem dentro dele. A rejeição só fica no trace por causa desse span: o código compartilhado não grava span para ela (registro: `ops.approval_queue`).
5. **Adulteração**: `make auditoria` → `cadeia íntegra`. Edite um número em `data/traces/audit.jsonl` (o arquivo é seu) e rode de novo → `registro N: conteúdo alterado (…)`. Restaure o arquivo depois. Explore no Phoenix, prove com a cadeia de hash.
6. **Filtrar no Phoenix** (aba *Spans*, campo de filtro): atributos aninhados, por exemplo `attributes["airflow"]["dag_run"]["run_id"] == "manual__…"` ou `attributes["agentready"]["business_date"] == "2026-11-25"`; `name == "agent.run"` lista todas as decisões.

O rollback no Bloco 5 (`make rollback CHG=…`) agora imprime **`Decisão original: <link>`** e aparece no Phoenix como `humano.rollback`, ligado ao `agent.run` que tomou a decisão.

## Bloco 5 na trilha stack (Fase 2)

Mesmo roteiro do Bloco 5 da trilha padrão, com as ferramentas da stack. TTD e TTR saem do mesmo registro de incidente.

1. **Injetar** (sem dizer qual): `make run ARGS='{"incident": "aleatorio"}'`.
2. **Detectar**: no Airflow, a folha **`observabilidade.resumo`** fica vermelha; o log dela tem a tabela dos 4 pilares (ou `make observe`). O histórico de cada pilar está no relatório (**:8090**). Registre a detecção: `make incidente ACAO=detectar`.
3. **Rastrear o impacto**: no Marquez (**:3000**, namespace `aurora`), parta de `bronze.conversions` (onde o feed ga4 chega) até `aurora_midia_diario.agente.executar`; a execução do agente traz o `trace_id`. As decisões candidatas a rollback: `make decisoes` (desde a injeção do último incidente; ou `DESDE=14:03` para outro horário de hoje), cada uma com o link do trace no Phoenix (Fase 3), onde o lote barrado e o veredito vermelho aparecem na mesma árvore da decisão.
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
| ensaio do Bloco 5 (`aleatorio` → `feed_parado`), feito pelo instrutor sem saber o tipo sorteado | **TTD 5,7 min · TTR 8,7 min** | **SC-006: TTD < 10 min** — repetir com alguém de fora antes do workshop |

### Fase 3 (traces, 2026-11-25)

Mesma máquina, stack já construída (sem checkout limpo nesta medição).

| Etapa | Tempo | Meta |
|---|---|---|
| execução completa em modo shadow (com traces) | 140–160 s | ≤ 5 min |
| do fim da tarefa do agente até o `agent.run` aparecer no Phoenix | < 2 s (já estava lá na primeira consulta) | **SC-004: ≤ 30 s** |
| mesma execução com o **coletor parado** | 195–205 s (+40–50 s: o envio desiste em 2 s por tarefa) | ≤ +60 s, decisões no log de auditoria (FR-012) |
| Phoenix parado no meio da execução → trace entregue depois que ele volta | 10 s | fila do coletor (FR-012) |
| `make parity` (7 cenários × 2 trilhas, agora com o trace do agente) | 114 s · 0 diferenças | **SC-002** |
| `make test-live` (7 execuções em shadow, derruba Marquez, Phoenix e coletor) | ~19 min | — |
| pico de RAM numa execução (todos os containers) | 3,0 GB (agendador 1,4 GB · Phoenix 0,44 GB · Marquez 0,40 GB · coletor 0,09 GB) | mínimo documentado: 8 GB livres |
| alguém de fora responde às 3 perguntas do auditor só no Phoenix | **a medir** (com cronômetro) | **SC-001: ≤ 5 min** |
| triagem do Bloco 5 pelo Phoenix × `trace last` / `lineage --since` | **a medir** (com cronômetro) | **SC-009: não mais lenta** |

### Fase 4 (fontes, política e snapshots, 2026-11-26)

| Medida | Resultado |
|---|---|
| Ingestão das 4 fontes (com a nova tentativa roteirizada do ga4) | **11,3 s** para 13.189 linhas (meta: ≤ 60 s) |
| Execução completa em modo shadow, do disparo ao fim | **175 s** (Fase 3: 155 s; +20 s com as 4 cargas e os marcos do lake) |
| Pico de memória somando todos os containers | **3,4 GB** (amostras a cada 5 s durante o `make test-live`) |
| Disco do lake por execução | **2,2 MB** na primeira execução completa (182 snapshots); **35 MB** depois de ~30 execuções num dia |
| Resolver o `centavos` por restauração (`make incidente ACAO=resolver`) | **2,8 s**, um comando; Gold e saúde das fontes iguais às da execução limpa |
| `make gold-em` (a Gold que o agente leu numa decisão) | **0,8 s** |
| Paridade 2.2.0 (`make parity`, 7 cenários pelas fontes + dlt) | **7/7 iguais** |
| SC-010: alguém que nunca viu a Fase 4 resolve o `centavos` só com este guia | **a medir** (com cronômetro, ≤ 10 min) |

## Estrutura

```
stack/
├── compose.yaml, Dockerfile     Airflow 3.3 + Postgres; imagem com 3 venvs isolados (dbt, datacontract-cli, agente)
├── compose.yaml (Fase 2)        + marquez-api, marquez-web, relatorio, db-init (bancos "marquez" e "phoenix" no mesmo Postgres)
├── compose.yaml (Fase 3)        + otel-collector (sem porta no host), phoenix (:6006)
├── Makefile                     up · run · approvals · rollback · parity · test · down · reset · contracts-sync
│                                + observe · incidente · decisoes · test-live (Fase 2) · traces · auditoria (Fase 3)
├── config/stack.yaml            agenda, tempo de aprovação, aprovadores, faixas e histórico mínimo da observabilidade
├── config/edr/config.yml        edr sem `dbt deps` (offline) e sem telemetria
├── config/otel-collector.yaml   Fase 3: recebe spans, marca projeto e tipo de span, fila em disco para o Phoenix
├── postgres-init/               bancos do Marquez (01) e do Phoenix (02), criados de forma idempotente
├── dags/aurora_midia_diario.py  o único DAG  ·  dags/_lineage_facets.py: trace_id do agente na linhagem
├── dbt/aurora/                  contrato (registro, quarentena, disjuntores) → Silver → Gold → observabilidade (obs_*)
├── agentready_stack/            tarefas do DAG, livro-razão, aprovações, paridade, observabilidade, incidentes, linhagem,
│                                telemetry.py (spans da stack, TRACEPARENT, links do Phoenix), rollback.py, trace_check.py
├── scripts/                     contracts-sync.sh (lint + testes gerados + Elementary) · lineage_live_check.py
└── tests/                       um teste por promessa (Fases 1, 2 e 3)
```

O código do agente, os contratos, a configuração e o corpus **não são copiados**: a raiz do repositório é montada somente leitura em `/opt/agentready`. Mudou na trilha padrão, mudou aqui.

## Problemas comuns

| Sintoma | Causa e solução |
|---|---|
| `docker: unknown command: docker compose` | falta o plugin Compose v2: `sudo apt install docker-compose-v2 docker-buildx` |
| execução nova fica "queued" | só roda uma execução por vez: há uma aprovação esperando em **Required Actions** |
| relatório em :8090 diz "ainda não gerado" | nenhuma execução terminou a etapa `observabilidade.relatorio`; se ela avisou `relatório de observabilidade não atualizado`, veja o log dela (o resto da execução não é afetado) |
| tarefas de teste do contrato sumiram (`campaigns_run` em vez de `campaigns.run` + `campaigns.test`) | o Cosmos guardou em cache um `dbt ls` antigo. Limpe o cache: `docker compose exec airflow-scheduler airflow variables delete cosmos_cache__aurora_midia_diario__contratos__verificar` (o DAG é relido em ~1 min). Desde a Fase 2 os testes gerados são trocados de forma atômica, o que evita o problema |
| no Marquez, a execução do agente não tem `trace_id` | veja o facet `agentready_trace`: `status: skipped_duplicate` = o agente foi **pulado** (mesmos dados: "já decidido para estes dados"), então não há trace. Escolha na lista de runs uma com `status: done`. O cabeçalho "LAST FINISHED" é da última execução do job, não da que você selecionou |
| Marquez vazio em :3000 | escolha o namespace **`aurora`** no canto superior; os eventos chegam ao fim de cada tarefa |
| `o warehouse DuckDB está aberto por outro processo` | um escritor por vez: espere a execução atual terminar |
| arquivos em `stack/` com dono errado | rode via `make` (ele cria `stack/.env` com o seu UID) |
| a execução não aparece na aba *Traces* do Phoenix | o span raiz chega quando a execução **termina** (depois da espera por aprovação). Use o link do log de `agente.executar` (ou `make traces`), ou a aba *Spans*. Se nada chega: `make logs SVC=otel-collector` (o coletor está no ar?) |
| o trace não tem `agent.run` | um passo anterior falhou e o agente não rodou (falha segura): o span raiz `dag_run.*` está vermelho e o grafo do Airflow mostra a tarefa que falhou. Ou o agente foi **pulado** (`agente.resultado` com `skipped_duplicate`: mesmos dados de antes) |
| o fechamento avisa `o trace … ainda não está no Phoenix` | o Phoenix ou o coletor caiu durante a execução. As decisões estão no log de auditoria (`make auditoria`); com o Phoenix fora, os spans esperam na fila do coletor e chegam quando ele voltar |
| a porta 6006 já está em uso | mude `PHOENIX_PORT` em `stack/.env` e rode `make up` |
| o `trace_id` de `make decisoes` agora é o da execução inteira | desde a Fase 3 o agente entra no trace da execução do Airflow: o mesmo id leva à execução toda, com a árvore do agente dentro |

Especificação, plano e decisões: [`specs/001-stack-production-track/`](../specs/001-stack-production-track/) (Fase 1), [`specs/002-stack-lineage-observability/`](../specs/002-stack-lineage-observability/) (Fase 2) e [`specs/003-stack-traces-dashboards/`](../specs/003-stack-traces-dashboards/) (Fase 3).
