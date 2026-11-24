# Trilha stack — o mesmo dia da Aurora, com ferramentas de produção

A trilha padrão do workshop roda tudo em Python escrito à mão, sem Docker, para que cada conceito fique visível. **Esta trilha roda o mesmo cenário com as ferramentas open source que times de dados usam em produção**: Airflow, dbt, Data Contract CLI e aprovação humana dentro do orquestrador.

A mensagem do workshop continua a mesma: **a lógica de decisão do agente não muda; muda a arquitetura ao redor dele.** Aqui ela ganha uma segunda parte: *"…e é assim que se roda isso em produção."* O comando `make parity` prova as duas ao vivo.

> **O que esta trilha NÃO é:** um substituto da demo do workshop (ela é opcional e mais pesada) nem um ambiente de produção (usuários e segredos fixos, só para estudo local).

## Pré-requisitos

- Docker Engine com os plugins **Compose ≥ 2.14** e **Buildx** (no Ubuntu: `sudo apt install docker-compose-v2 docker-buildx`)
- **≥ 4 CPUs** e **≥ 8 GB de RAM livre** (o `make up` confere e avisa)
- Internet só na primeira vez (baixar imagens e pacotes); depois roda offline

## Início rápido

```bash
cd stack
make up                                   # constrói a imagem, sobe tudo e espera ficar saudável
make run ARGS='{"reset_scenario": true}'  # gera o cenário da manhã e roda o dia inteiro
make parity                               # prova: as duas trilhas decidem igual
make test                                 # testes da trilha stack (dois ambientes Python)
make down                                 # para (mantém os dados)   ·   make reset: apaga os dados da trilha
```

Interface do Airflow: **http://localhost:8080**

| Usuário | Senha | Papel |
|---|---|---|
| `instrutor` | `instrutor` | administrador: dispara execuções e acompanha |
| `aprovadora` | `aprovadora` | **única** pessoa que pode aprovar ou rejeitar ações do agente |

> ⚠️ Usuários e senhas fixos (`config/passwords.json`, fora do git) servem **apenas para estudo local**. Não exponha esta stack em rede.

Na primeira subida, o Airflow já dispara a execução agendada mais recente; como a Bronze está vazia, ela gera o cenário sozinha.

## O dia em um DAG: `aurora_midia_diario`

```
 ingestao ──▶ contratos ────────────────────────────────▶ gold ──▶ agente ──▶ aprovacao ──▶ fechamento
              │ lint (datacontract lint + gera testes)     dbt      o MESMO   HITL na       marca d'água
              │ verificar (dbt: quarentena, disjuntor,               agente    interface     + resumo
              │            Silver + testes do contrato)              da trilha do Airflow
              └ alerta_qualidade (folha: só problemas NOVOS)         padrão
```

Parâmetros da execução (formulário "Trigger" no Airflow ou `make run ARGS='{...}'`):

| Parâmetro | Padrão | O que faz |
|---|---|---|
| `reset_scenario` | `false` | gera o cenário do zero (reset completo da trilha stack) |
| `backfill_meta` | `false` | chegam os lotes atrasados da Meta (o feed volta a ficar fresco) |
| `incident` | `nenhum` | injeta um incidente do Bloco 5: `centavos`, `renomeacao`, `lote_duplicado`, `feed_parado`, `aleatorio` |
| `autonomy_override` | `manter` | escada de autonomia global: `shadow`, `supervised`, `guarded`, `full`, `limpar` |
| `brain` | `rules` | `claude` usa o Claude (precisa de `ANTHROPIC_API_KEY` em `stack/.env`) |
| `gullible` | `false` | Bloco 3: o agente "acredita" no briefing com injeção de prompt |

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
make parity                    # os três cenários   ·   make parity SCENARIO=manha
```

Cada trilha roda num processo isolado, com o mesmo cenário, o mesmo horário de referência e no mesmo dia: a padrão com `pipeline.run()` (Python à mão), a stack com `dbt build`. Depois, **o mesmo agente** decide nas duas. O comando compara a Gold campanha×dia (ao centavo), a saúde das fontes e cada decisão do agente, e termina com código 0 só se tudo for igual.

| Cenário | O que testa |
|---|---|
| `manha` | o cenário plantado: Meta parada, lote duplicado, sujeira, lote com bug |
| `pos_backfill` | depois que os lotes atrasados da Meta chegam |
| `supervisionado` | toda ação vira pedido de aprovação |

## Mapa de substituição: cada ferramenta substitui um módulo

Regra da trilha (constituição, Princípio VI): **ferramenta que não substitui um módulo da trilha padrão não entra.**

| Ferramenta (Fase 1) | Versão | Substitui (trilha padrão) | Bloco |
|---|---|---|---|
| **Apache Airflow** (DAG, pool, agenda) | 3.3.2 | a ordem das etapas em `pipeline.run()` e os comandos `setup` / `pipeline` / `backfill-meta` / `incident inject` (agora parâmetros do DAG) | 1, 5 |
| **Airflow Human-in-the-loop** | provider padrão | `agentready approvals` / `approve` / `reject` (a fila de aprovação na CLI) | 4 |
| **dbt-core + dbt-duckdb** | 1.10.23 · 1.11.1 | a materialização de `contracts.apply()` (Silver, Quarentena, `batch_status`), `pipeline.build_gold()` e `pipeline.write_health()` | 1, 2 |
| **astronomer-cosmos** | 1.16.0 | a "cola" em Python que rodava as etapas em sequência: cada modelo e teste dbt vira uma tarefa visível no Airflow | 1 |
| **Data Contract CLI** | 1.2.11 | a leitura dos tipos do contrato para checar a Silver: gera os testes dbt a partir do ODCS, e acrescenta o `lint` dos contratos (um portão novo) | 1 |

**Substituição parcial, com honestidade:**

- **`contracts.violation_exprs()` continua compartilhado.** Nenhuma ferramenta open source faz quarentena **linha a linha** com **disjuntor por lote**: Data Contract CLI, Soda e Great Expectations testam o conjunto de dados inteiro. Então as regras ODCS continuam virando SQL num único lugar, chamado de dentro do dbt. O mesmo vale para `pipeline.freshness()` (a regra de frescor), para a paridade ser exata.
- **Postgres não substitui módulo nenhum:** é o banco de metadados exigido pelo próprio Airflow, parte do orquestrador.

**Achado real:** o `datacontract lint` desta trilha mostrou que os contratos originais **não eram ODCS válido** (declaravam v3.0.2 mas usavam o tipo `timestamp`, a regra `rule: validValues` e `partitionBy` dentro do SLA). Eles foram migrados para **ODCS v3.1.0**; veja a nota em [`docs/00-validacao-do-projeto.md`](../docs/00-validacao-do-projeto.md).

## Lacunas conhecidas (diga isso ao público)

- **O incidente `centavos` passa nos contratos.** Os valores continuam numéricos e ≥ 0, então o lote é aprovado e o alerta fica verde, enquanto o ticket médio na Silver salta de ~R$ 199 para ~R$ 20 mil. Quem pega isso é a observabilidade de **distribuição** (Fase 2). É a mesma lição do Bloco 5: contrato ≠ observabilidade.
- **Linhagem, traces e painéis** continuam como na trilha padrão (`agentready lineage`, `trace`, `observe`) até as Fases 2 e 3.
- **O servidor MCP e a camada semântica** não mudaram: o agente desta trilha usa as mesmas capacidades dentro do processo.
- **dbt-core 1.10** já está fora do suporte regular da dbt Labs; atualizar para uma versão suportada é um item da próxima fase (os testes e a paridade dizem se a atualização mudou algo).
- **Depois de mudar um contrato**, o Cosmos só mostra as tarefas de teste novas quando o DAG é lido de novo (alguns segundos; ou reinicie o `airflow-dag-processor`).

## Roteiro das próximas fases

Cada fase troca mais um módulo escrito à mão por uma ferramenta de produção, e deixa o cenário mais realista.

| Fase | Ferramenta | Substitui | Bloco | Fica mais realista |
|---|---|---|---|---|
| **2** | **OpenLineage + Marquez** | o comando `lineage` | 4, 5 | linhagem emitida pelo próprio pipeline (o Airflow já tem provider OpenLineage), até a decisão do agente |
| **2** | **Elementary** (observabilidade de dados no dbt) | `observability.py` | 5 | detecção de anomalia de volume e distribuição: **pega o `centavos`** que passa no contrato |
| **3** | **OpenTelemetry Collector + Phoenix ou Langfuse + Grafana** | `tracing.py` e o log JSONL com cadeia de hash | 4 | traces de pipeline e de agente num só lugar, com painéis |
| **4** | **APIs simuladas (FastAPI) + dlt** | a carga estática de `generate.py` | 1 | lotes atrasados, duplicados e quebrados chegando como na vida real |
| **4** | **Open Policy Agent (OPA)** | a aplicação de `config/guardrails.yaml` | 3 | guardrails como política versionada e testável, fora do agente |
| **4** | **DuckLake ou Iceberg em MinIO** | o arquivo único do warehouse | 5 | snapshots: rollback do incidente vira *time travel* de verdade |
| **5** *(opcional)* | **OpenMetadata ou DataHub** | — (catálogo) | 1, 2 | glossário, donos e contratos num só lugar |

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

## Estrutura

```
stack/
├── compose.yaml, Dockerfile     Airflow 3.3 + Postgres; imagem com 3 venvs isolados (dbt, datacontract-cli, agente)
├── Makefile                     up · run · approvals · rollback · parity · test · down · reset · contracts-sync
├── config/stack.yaml            agenda, tempo de aprovação, aprovadores
├── dags/aurora_midia_diario.py  o único DAG
├── dbt/aurora/                  contrato (registro, quarentena, disjuntor) → Silver → Gold
├── agentready_stack/            tarefas do DAG, livro-razão do agente, aprovações, paridade (CLI agentready-stack)
├── scripts/contracts-sync.sh    datacontract lint + testes dbt gerados a partir do ODCS
└── tests/                       um teste por promessa da Fase 1
```

O código do agente, os contratos, a configuração e o corpus **não são copiados**: a raiz do repositório é montada somente leitura em `/opt/agentready`. Mudou na trilha padrão, mudou aqui.

## Problemas comuns

| Sintoma | Causa e solução |
|---|---|
| `docker: unknown command: docker compose` | falta o plugin Compose v2: `sudo apt install docker-compose-v2 docker-buildx` |
| execução nova fica "queued" | só roda uma execução por vez: há uma aprovação esperando em **Required Actions** |
| `o warehouse DuckDB está aberto por outro processo` | um escritor por vez: espere a execução atual terminar |
| arquivos em `stack/` com dono errado | rode via `make` (ele cria `stack/.env` com o seu UID) |

Especificação, plano e decisões: [`specs/001-stack-production-track/`](../specs/001-stack-production-track/).
