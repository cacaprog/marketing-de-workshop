# Runbook — Dados Prontos para IA Agêntica (Aurora Cosméticos)

Guia de operação de todas as opções e comandos do projeto. São duas trilhas que rodam **o mesmo agente** sobre o
mesmo cenário:

| Trilha | Onde | Para quê | Pré-requisitos |
|---|---|---|---|
| **Padrão** | raiz do repo | demo determinística em Python + DuckDB, sem Docker | `uv`, Python 3.11+ |
| **Stack** | `stack/` | a mesma história em ferramentas de produção (Airflow, dbt, DuckLake, OPA, Marquez, Phoenix…) | Docker Compose ≥ 2.14, ≥ 4 CPUs, ≥ 8 GB de RAM livre |

> Regras de ouro
> - Na stack, use sempre `make` dentro de `stack/`, nunca `docker compose` direto (o `make` grava o `.env` com o seu UID).
> - Ensaios e validações ao vivo: `autonomy_override: "shadow"` (o agente decide, mas não executa).
> - Aprovações humanas (HITL) são **suas**: aprove ou rejeite você mesmo no Airflow (**Required Actions**).
> - Não consulte o lake enquanto uma execução está ingerindo (o DuckDB aceita um só escritor por vez).

---

## 1. Trilha padrão (raiz do repo)

### 1.1 Preparação

```bash
make install        # uv sync --extra dev
make setup          # gera o cenário e roda o pipeline (reset completo) — rode no dia do workshop
make test           # suíte padrão (97 testes, sem rede e sem modelo)
make clean          # apaga data/*.duckdb e traces/
```

### 1.2 Roteiro do workshop

```bash
make demo           # roteiro completo, com pausas (blocos 0..5)
make demo-3         # um bloco só (0, 1, 2, 3, 4 ou 5)
uv run agentready demo all --no-pause                 # sem pausas
uv run agentready demo 5 --incident centavos          # Bloco 5 com um incidente escolhido (ou --incident random)
```

### 1.3 Todos os comandos `uv run agentready …`

| Comando | O que faz | Opções |
|---|---|---|
| `setup` | gera o cenário e roda o pipeline (reset completo) | — |
| `demo {0..5\|all}` | roteiro narrado | `--no-pause`, `--incident <tipo\|random>` |
| `pipeline` | Bronze → contratos → Silver → Gold | — |
| `agent {naive\|ready}` | roda um agente (o ingênuo ou o pronto); com um modelo de linguagem, `naive` = sem contexto e `ready` = com contexto | `--brain rules\|claude\|local` (padrão `rules`, determinístico), `--llm-model <m>`, `--llm-url <url>`, `--gullible` (obedece a injeção no corpus), `--request "<pedido>"` |
| `ask "<pergunta>"` | pergunta em linguagem natural → camada semântica | — |
| `health` | frescor, quarentena e versões | — |
| `quarantine [tabela]` | inspeciona a dead-letter queue | `--limit N` |
| `budgets` | estado vivo das campanhas e histórico | — |
| `approvals` | fila de aprovação humana | — |
| `approve <REQ-…>` / `reject <REQ-…>` | decide um pedido | `--by <nome>` |
| `rollback <CHG-…>` | desfaz uma alteração do agente | `--by <nome>` |
| `autonomy <nível>` | override global: `shadow`, `supervised`, `guarded`, `full`, `clear` | — |
| `trace [id\|prefixo\|last]` | lista traces ou mostra um | — |
| `verify` | verifica a cadeia de hash do log de auditoria | — |
| `observe` | os 5 pilares de observabilidade | — |
| `lineage [nó]` | impacto a jusante de um nó | `--since <data>` |
| `perguntas` | 8 perguntas de negócio (`config/perguntas.yaml`) respondidas pelo mesmo modelo com e sem contexto, lado a lado | `--brain rules\|claude\|local`, `--llm-model`, `--llm-url`, `--ids <id,…>`, `--no-pause`, `--sim`, `--mostrar <arquivo>` (reapresenta sem modelo nem rede) |
| `compare` | compara cérebros com e sem contexto, com nota contra a verdade do cenário (grava em `data/compare/`) | `--brains rules,claude[:<m>],local:<m>[@url]`, `--runs N`, `--condicoes ambas\|com\|sem`, `--modo acoes\|perguntas`, `--llm-url`, `--sim` |
| `chat` | conversa livre com um modelo, só leitura | `--brain`, `--llm-model`, `--llm-url`, `--sem-contexto` |
| `incident inject <tipo>` / `detect` / `resolve` / `reveal` / `list` | ciclo de vida de um incidente | tipos abaixo |
| `backfill-meta` | corrige o feed da Meta (chegam os lotes atrasados) | — |
| `mcp` | servidor MCP (stdio); também `make mcp` | — |

**Tipos de incidente (Bloco 5):**

| Tipo | O que o upstream fez | Pilar que pega |
|---|---|---|
| `centavos` | passou a enviar `order_value_brl` e `discount_brl` em centavos (×100) | Distribuição |
| `renomeacao` | renomeou `campaign_id` → `utm_campaign` | Esquema |
| `lote_duplicado` | reenviou o lote de ontem sem idempotência | Volume |
| `feed_parado` | o token do ga4 expirou e o lote de ontem nunca chegou | Frescor |

**Modelos de linguagem (opcional):** a chave e o servidor ficam num `.env` na raiz, que o git ignora:

```bash
uv sync --extra llm --extra dev                       # o extra llm só é preciso para o Claude
cp .env.example .env && chmod 600 .env                # ANTHROPIC_API_KEY, AGENTREADY_LLM_MODEL, AGENTREADY_LLM_BASE_URL
uv run --env-file .env agentready perguntas --brain claude --llm-model haiku
uv run --env-file .env agentready perguntas --brain local --llm-model qwen2.5:14b
uv run agentready perguntas --mostrar data/compare/perguntas-<data>.json   # no palco: sem modelo nem rede
```

O Claude aceita `--llm-model opus|sonnet|haiku|fable` ou o id completo (padrão: `AGENTREADY_MODEL`, depois o Opus).
O cérebro `local` fala com qualquer servidor compatível com OpenAI (Ollama em `:11434/v1`, llama.cpp em `:8081/v1`).
Aumente o contexto do Ollama e limite a resposta do llama.cpp (`AGENTREADY_LLM_MAX_TOKENS`): detalhes em
`docs/06-comparar-modelos.md`. A trilha stack só aceita `rules` e `claude`.

**Política (guardrails):** o avaliador padrão é o Python local. A variável `AGENTREADY_POLICY_EVALUATOR`
escolhe outro avaliador (a stack usa o OPA). Os limites ficam em `config/guardrails.yaml`, compartilhado pelas
duas trilhas.

---

## 2. Trilha stack (`cd stack`)

### 2.1 Ciclo de vida

```bash
make help           # lista os comandos
make check          # confere Compose, CPUs e RAM
make up             # sobe tudo e espera ficar saudável (cria .env e config/passwords.json se faltarem)
make down           # para os serviços e MANTÉM os dados
make reset          # para tudo e APAGA os dados da trilha stack (lake, ops.duckdb, fontes, Postgres, linhagem, traces…)
make logs SVC=airflow-scheduler    # acompanha os logs de um serviço
make doctor         # versões de cada ambiente e compatibilidade do DuckDB
```

`make reset` só apaga `stack/data/` deste checkout; a trilha padrão (`../data`) nunca é tocada.
Depois de mudar `compose.yaml` ou variáveis de ambiente, rode `make up` de novo para recriar os containers.

### 2.2 Endereços e usuários

| Serviço | URL | Para quê |
|---|---|---|
| Airflow | http://localhost:8080 | DAG `aurora_midia_diario`, execuções, aprovações (**Required Actions**) |
| Linhagem (Marquez) | http://localhost:3000 | grafo de linhagem, namespace `aurora` |
| Relatório (Elementary) | http://localhost:8090 | testes de contratos e os 4 pilares |
| Traces (Phoenix) | http://localhost:6006 | um trace por execução, projeto `aurora` |
| Fontes simuladas | http://localhost:8000/docs | as 4 APIs (ads, ga4, meta_capi, catálogo); só em `127.0.0.1` |

Usuários (só estudo local, em `config/passwords.json`): **instrutor** (opera) e **aprovadora** (aprova pedidos).

### 2.3 Disparar o dia: `make run ARGS='{…}'`

```bash
make run ARGS='{"reset_scenario": true, "autonomy_override": "shadow"}'   # o ensaio padrão
```

| Parâmetro | Valores (padrão em **negrito**) | Efeito |
|---|---|---|
| `reset_scenario` | `true` \| **`false`** | recomeça o cenário do zero |
| `autonomy_override` | **`manter`**, `shadow`, `supervised`, `guarded`, `full`, `limpar` | nível de autonomia nesta execução |
| `brain` | **`rules`** \| `claude` | cérebro do agente (`claude` precisa de chave de API) |
| `gullible` | `true` \| **`false`** | agente obedece à injeção no corpus (a política tem de negar) |
| `incident` | **`nenhum`**, `centavos`, `renomeacao`, `lote_duplicado`, `feed_parado` | injeta um incidente do Bloco 5 |
| `backfill_meta` | `true` \| **`false`** | chegam os lotes atrasados da Meta |
| `falhas_upstream` | **`padrao`**, `nenhuma`, `todas` | plano de falhas das fontes (o padrão faz o ga4 cair uma vez e ser re-tentado) |
| `fonte_fora_do_ar` | **`nenhuma`**, `ads`, `ga4`, `meta_capi`, `catalogo` | derruba uma fonte; as outras seguem |
| `disjuntor_distribuicao` | **`compartilhado`**, `ligado`, `desligado` | disjuntor do pilar de distribuição |
| `comentario` | texto livre | anotação da execução |

Uma execução leva cerca de 3 minutos. Ficam vermelhas **por desenho** apenas as folhas de alerta
(`contratos.alerta_qualidade`, `observabilidade.testes`, `observabilidade.resumo`) quando há achados.

> Logo depois de um `make up` num checkout novo, o primeiro `make run` pode ser recusado (o DAG ainda não foi
> registrado). Espere um minuto e rode de novo.

### 2.4 Observar

```bash
make fontes         # última carga de cada fonte: status, lotes novos/retirados, linhas, novas tentativas
make observe        # os 4 pilares de dados da última execução
make decisoes       # decisões do agente desde o último incidente (ou DESDE=HH:MM / DESDE=AAAA-MM-DDTHH:MM)
make traces         # últimas execuções com o link do trace no Phoenix
make auditoria      # verifica a cadeia de hash do log de auditoria
```

### 2.5 Aprovações e rollback

```bash
make approvals                  # pedidos aguardando aprovação humana
# aprovar/rejeitar: Airflow → Required Actions (entre como aprovadora)
make rollback CHG=CHG-xxxx      # desfaz uma alteração do agente, ligada ao trace da decisão original
```

A política é reavaliada no momento da aprovação: se o OPA estiver fora do ar, a aprovação é **negada** (falha
fechada).

### 2.6 Política como código (OPA)

```bash
make politica ACAO='ajustar C01 5200'   # a política permitiria? (não executa nada) → PERMITIDO / NEGADO (<regra>)
make politica ACAO='pausar C06'
make politica-testes                    # opa test com cada caso de stack/policy/testes/casos.yaml
```

Os arquivos são `stack/policy/guardrails.rego` (as regras) e `config/guardrails.yaml` (os limites,
compartilhados). Para mostrar uma falha, edite um limite **numa cópia** e rode `make politica-testes`.

### 2.7 Snapshots do lake (DuckLake)

```bash
make snapshots                                              # marcos por etapa (ingestao.*, contratos, agente, gold_observabilidade…)
make consultar-em TABELA=gold.campaign_daily EM=3950        # uma tabela num snapshot…
make consultar-em TABELA=gold.campaign_daily EM=2026-11-26T15:40 FILTRO="campaign_id='C01'"   # …ou num horário
make gold-em DECISAO=CHG-xxxx                               # a Gold que o agente leu para uma decisão (trace_id, CHG-… ou REQ-…)
make restaurar PARA=CK-xxxxxxxx MOTIVO="volta antes do centavos"   # restaura (vira um snapshot novo)
```

O restaurar **recusa** quando há execução ativa, quando o alvo é anterior ao último reset, quando o alvo não
existe, quando é igual ao estado atual, ou quando o alvo não tem `gold.campaign_daily`. Errou? Rode
`make restaurar PARA=<snapshot anterior>`: a restauração também pode ser desfeita.

### 2.8 Incidentes (Bloco 5)

```bash
make run ARGS='{"incident": "centavos", "autonomy_override": "shadow"}'   # injeta
make incidente ACAO=detectar      # o que os pilares viram
make incidente ACAO=resolver      # a fonte volta ao normal e o lake é restaurado ao último estado limpo
make incidente ACAO=revelar       # mostra qual foi a causa
make incidente ACAO=listar
```

### 2.9 Testes e comparações

```bash
make test                         # suíte da stack (~30 min; precisa da stack no ar) + coletor + opa test
make parity SCENARIO=todos        # o agente decide igual nas duas trilhas? (manha, pos_backfill, supervisionado,
                                  # incidente_centavos, incidente_renomeacao, incidente_lote_duplicado, incidente_feed_parado)
make test-live                    # validação ao vivo das fases 2–4 (11 execuções; derruba Marquez, Phoenix, coletor e OPA; ~45 min)
make contracts-sync               # regenera os testes dbt a partir dos contratos ODCS
```

---

## 3. Roteiros prontos

**Ensaio rápido da stack (≈ 5 min)**
1. `cd stack && make up`
2. `make run ARGS='{"reset_scenario": true, "autonomy_override": "shadow"}'`, e acompanhe no Airflow.
3. `make fontes` → `make snapshots` → `make traces` (abra o link) → `make politica ACAO='ajustar C01 5200'`.

**Incidente resolvido por snapshot**
1. `make run ARGS='{"incident": "centavos", "autonomy_override": "shadow"}'`
2. `make incidente ACAO=detectar` (o pilar de distribuição dispara)
3. `make snapshots`, para achar o último `gold_observabilidade` limpo
4. `make incidente ACAO=resolver` (ou `make restaurar PARA=CK-…`), depois `make run`

**Fonte fora do ar**: `make run ARGS='{"fonte_fora_do_ar": "ga4", "autonomy_override": "shadow"}'` → `make fontes`
mostra ga4 `falhou` e as outras carregadas.

**Agente enganável**: `make run ARGS='{"gullible": true, "autonomy_override": "shadow"}'` → a política nega.

**Aprovação humana**: `make run ARGS='{"autonomy_override": "supervised"}'` → `make approvals` → aprove ou rejeite
no Airflow como aprovadora → `make rollback CHG=…` para desfazer.

---

## 4. Problemas comuns

| Sintoma | Causa provável | O que fazer |
|---|---|---|
| `make test` diz "a stack não está no ar" | os testes leem o banco do Airflow | `make up` antes |
| `make run`: "não consegui autenticar" ou "recusou a execução" | Airflow ainda subindo, ou DAG não registrado | espere 1 min; `make logs SVC=airflow-dag-processor` |
| comando do lake sai com código 2 ("lake ocupado") | uma execução está escrevendo | espere a execução terminar |
| `restaurar` recusado | uma das proteções da seção 2.7 | leia a mensagem; escolha um `CK-…` de `gold_observabilidade` |
| ga4 com "1 nova tentativa" | é o plano de falhas padrão (desejado) | `falhas_upstream: "nenhuma"` para desligar |
| aprovação negada com o OPA fora | falha fechada (desejado) | suba o OPA (`make up`) e peça de novo |
| arquivos de `stack/data` com dono root | criados pelo Docker antes do `.env` | `make reset` (usa um container para apagar) |
| mudança no compose não fez efeito | containers antigos | `make up` |

Mais detalhes: `stack/README.md` (guia da stack e tempos medidos), `docs/01-roteiro-do-instrutor.md` (roteiro
por bloco), `docs/02-exercicios.md` (exercícios), `docs/06-comparar-modelos.md` (modelos com e sem contexto) e
`docs/07-skills-harness-e-camada-de-contexto.md` (como esta abordagem se compara a skills).
