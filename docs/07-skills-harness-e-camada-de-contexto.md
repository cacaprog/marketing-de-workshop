# Skills, harness e camada de contexto: o que muda

Muita gente está falando de *harness engineering* e de *skills* como o jeito de fazer modelos agirem bem. Este texto mostra como essas ideias se relacionam com a abordagem deste projeto e por que elas **se complementam, mas não se substituem**.

Em uma frase: **uma skill ensina o modelo a se comportar; a camada de contexto faz os dados e as ferramentas se comportarem certo, qualquer que seja o modelo.**

## As três coisas que costumam ser misturadas

| Termo | O que é | Onde a "regra" mora |
|---|---|---|
| **Harness engineering** | O laço em volta do modelo: quais ferramentas ele recebe, permissões, novas tentativas, gestão de contexto, quando parar | No código que roda o modelo (Claude Code, Agent SDK, um laço próprio) |
| **Skill** | Um pacote de instruções, às vezes com scripts e arquivos de referência, carregado no contexto quando é relevante | Em texto que o modelo lê (em geral um `SKILL.md`) |
| **Camada de contexto** (este projeto) | Modelo semântico, contratos de dados e guardrails nos dados, mais capacidades que fazem valer as regras | Em YAML e Python, verificados de forma determinística |

## Cinco diferenças

### 1. Orientação contra garantia

Uma skill pode dizer "nunca pause uma campanha sem aprovação" ou "awareness não usa ROAS", mas o modelo ainda pode ignorar. Aqui essas regras são código: `src/agentready/capabilities.py` (pré-condições, guardrails, fila de aprovação, rollback) avalia a política de `config/guardrails.yaml` por meio de `src/agentready/policy.py`. Na trilha stack, o OPA avalia as mesmas regras, e a verificação de paridade dá zero diferenças. O modelo pode propor qualquer coisa; quem decide é o backend.

### 2. O próprio projeto testou isso

Na comparação de modelos (`docs/06-comparar-modelos.md`), a orientação estava nas descrições das ferramentas, que é basicamente o que uma skill faz. Mesmo **com contexto**, o Claude Haiku 5.5 deu **ROAS 0,60** para a C05, uma campanha de awareness, porque a regra "awareness não usa ROAS" existia só em texto, e ele não leu esse texto. O Opus leu e acertou.

Mais texto no prompt não resolveu. A spec 006 resolveu: a regra foi para os dados (`not_applicable` em `semantic/marketing.semantic.yaml`, status `nao_se_aplica`). Na nova execução, o Haiku respondeu **"não se aplica"**.

Essa é a diferença num exemplo só: com a skill, você depende de o modelo ler com atenção. Com os dados certos, o número errado nem chega a existir.

### 3. Independência de modelo

O agente `--brain rules` não usa modelo de linguagem nenhum e mesmo assim toma ações certas e governadas. Isso mostra que a inteligência está nos dados e nas capacidades. Com só uma skill, a qualidade acompanha o modelo. Na mesma rodada de 8 perguntas (uma execução por modelo, 27/11/2026):

| | qwen2.5:14b (local) | Claude Haiku 5.5 | Claude Opus 5.5 |
|---|---|---|---|
| Sem contexto | 0 certas | 4 certas · 2 erradas · 2 inventou número | 5 certas + 1 desconhecido correto · 2 erradas |
| Com contexto | 4 certas | 6 certas + 1 desconhecido correto · 1 inventou número | 7 certas + 1 desconhecido correto |
| Tempo (8 perguntas) | — | 112 s sem · 32 s com | 158 s sem · 40 s com |

O "1 inventou número" do Haiku com contexto é exatamente o ROAS 0,60 da C05, corrigido depois pela spec 006.

### 4. Auditoria e reversibilidade

Uma skill não deixa registro oficial. Aqui há o `audit.jsonl` encadeado por hash com `verify_chain()`, o log de mudanças com rollback, classes de reversibilidade por ferramenta (R0, R1, R2) e aprovação humana (HITL). É isso que interessa a quem cuida de governança ou de compliance.

### 5. Uma fonte, vários consumidores

O modelo semântico alimenta a tabela do Bloco 2, o servidor MCP, os avaliadores e o dbt na trilha stack. Uma skill só serve ao agente que a carrega; dashboards e pessoas nunca a veem.

## Onde as skills entram

Skills são ótimas para **saber fazer**: como conduzir uma análise, qual ferramenta chamar primeiro, como formatar um briefing, o estilo da casa. São baratas de mudar, portáveis entre agentes e só entram no contexto quando precisam. As descrições de ferramentas em `src/agentready/toolsets.py` e o prompt de sistema neutro já ficam nessa camada.

Uma regra prática:

> **Skill = como agir. Camada de dados = o que é verdade. Capacidade/guardrail = o que é permitido.**
> Se errar custa dinheiro ou quebra uma política, a regra não pode morar só numa skill.

Uma skill do `agentready` poderia ensinar um agente a usar bem as ferramentas MCP, e os guardrails continuariam pegando os erros quando ele não usasse. A onda de "harness + skills" é sobre deixar os modelos **mais capazes**. Este projeto é sobre deixá-los **confiáveis para mexer em dados e ações reais**, o que skills sozinhas não garantem.

## Ganchos para posts

Frases curtas, cada uma apoiada num fato acima:

- "Uma skill ensina o modelo a se comportar. Os dados certos impedem que ele erre."
- "Mesmo com contexto, um modelo menor calculou ROAS de uma campanha de awareness. A correção não foi um prompt melhor: a regra foi para os dados, e ele passou a responder 'não se aplica'."
- "Skill = como agir. Dados = o que é verdade. Guardrail = o que é permitido."
- "Se errar custa dinheiro, a regra não pode morar só em texto que o modelo talvez leia."
- "O mesmo agente sem modelo de linguagem nenhum toma decisões certas. A inteligência estava nos dados."
- "Com a camada de contexto, as respostas ficaram de 3,5 a 4 vezes mais rápidas: a limpeza não precisa ser refeita a cada pergunta."

**Cuidado ao publicar:** os números vêm de **uma execução por modelo** num cenário fictício (Aurora Cosméticos). Eles ilustram o padrão, não medem qual modelo é melhor. Resultados de modelos de linguagem variam a cada execução.
