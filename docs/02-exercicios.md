# Exercícios dos participantes

Trabalhe em dupla (um perfil técnico + um de negócio). Para voltar ao estado inicial a qualquer momento: `uv run agentready setup`.
Todos os comandos abaixo assumem o prefixo `uv run`.

## Bloco 1 · Contratos e quarentena

1. **Leia o contrato.** Abra `contracts/conversions.odcs.yaml`. Quais regras pegaram cada motivo de `agentready quarantine`?
2. **Faixa plausível.** Adicione `maximum: 5000` em `logicalTypeOptions` de `order_value_brl`. Rode `agentready pipeline`. Algo novo entrou em quarentena? *Guarde esta regra: ela vai importar no Bloco 5.*
3. **Sensibilidade do disjuntor.** Mude `maxQuarantineRate` para `0.005`. Quantos lotes são barrados agora (`agentready health`)? Qual o custo de um disjuntor sensível demais?
4. **(Negócio) O SLA é uma decisão de negócio.** Mude o `latency` de conversões de 24 para 96 horas e rode `agentready pipeline` e `agentready agent ready`. O que o agente fez com a Meta? Quem na empresa deveria ser dono desse número?
5. Desfaça as mudanças 3 e 4 (`git checkout contracts/` ou edite de volta) e rode `agentready setup`.

**Trilha stack (Fase 4, opcional):** rode `make run ARGS='{"reset_scenario": true, "autonomy_override": "shadow"}'` e ache o lote reenviado do ga4 duas vezes: em `make fontes` (chegou pela fonte, com o resto) e na quarentena/`batch_status` (barrado pelo contrato). Por que a ingestão **não** deveria descartar a duplicata sozinha?

## Bloco 2 · Camada semântica

1. `agentready ask "CAC por canal nos últimos 7 dias"`. Por que a Meta aparece como NULL?
2. **Nova métrica.** Em `semantic/marketing.semantic.yaml`, crie:
   ```yaml
   ticket_medio:
     label: Ticket médio líquido (R$)
     type: ratio
     numerator: net_revenue
     denominator: orders
     synonyms: [ticket médio, valor médio do pedido]
   ```
   Teste: `agentready ask "ticket médio por campanha"`.
3. Tente uma métrica que não existe (`agentready ask "lucro por campanha"`). Por que recusar é melhor do que adivinhar?
4. **(Negócio)** Escrevam em uma frase a definição oficial de "campanha lucrativa" para a Aurora. Ela cabe no YAML? O que falta (margem, LTV)?

## Bloco 3 · MCP e guardrails

1. `agentready agent ready --gullible`. Encontre no output a pré-condição que barrou a injeção.
2. **Injeção sutil.** Em `corpus/briefings/C06.md`, troque "R$ 35.000" por "R$ 3.850" (+10%) e rode `agentready agent ready --gullible`. Ela passa? Por quê? (Dica: `config/guardrails.yaml` e `config/autonomy.yaml`.) Conclusão: guardrails **limitam o dano**, não eliminam o risco. Que controle adicional vocês proporiam (ex.: proibir justificativas baseadas em fonte não confiável)?
3. **Trava humana.** Pause manualmente uma campanha ou trave-a:
   `python -c "from agentready.db import connect; connect().execute(\"UPDATE ops.campaigns SET locked_by_human=TRUE WHERE campaign_id='C01'\")"`
   e rode o agente. O que mudou?
4. **Conecte um cliente MCP** (README → "Conectar o servidor MCP") e peça: *"Analise as campanhas e proponha ajustes; não execute nada sem me mostrar"*.
5. **(Negócio) Classifique em R0–R3** cinco ações reais de marketing da sua empresa (ex.: enviar e-mail para a base, mudar lance, criar público, apagar criativo, alterar preço).

**Trilha stack (Fase 4, opcional):** (a) pergunte à política sem rodar o agente: `make politica ACAO='ajustar C01 4800'` e `ACAO='ajustar C01 4810'` — onde fica a fronteira e de onde vem o número? (b) Em `stack/policy/testes/casos.yaml`, acrescente um caso para uma campanha travada por um humano tentando ser pausada e rode `make politica-testes`. (c) Discuta: o que muda quando a regra é um arquivo testado e versionado, fora do código do agente?

## Bloco 4 · Rastreabilidade e autonomia

1. **Interrogatório do auditor.** Com `agentready trace last` e o HTML em `traces/`, respondam:
   - Por que o orçamento do C01 subiu? Com base em qual número?
   - Qual versão do modelo semântico e dos guardrails estava valendo?
   - Por que nada foi feito com C03?
2. `agentready autonomy shadow` → `agentready agent ready` → `agentready budgets`. Algo mudou? Depois `agentready autonomy clear`.
3. `agentready approvals` → `agentready approve <REQ>`. Antes de aprovar, trave a campanha (exercício 3.3). O que acontece?
4. **Adulteração.** Edite um número em `traces/audit.jsonl` e rode `agentready verify`.
**Trilha stack (Fase 3, opcional):** os exercícios 1 e 4 no Phoenix (`stack/`, veja `stack/README.md` → "Bloco 4 na trilha stack").
   - **1 (stack):** `make traces` → abra o link da última execução e responda às mesmas três perguntas pelos spans (`tool.adjust_campaign_budget`, `tool.get_campaign_performance`, `agent.reasoning`).
   - **4 (stack):** `make auditoria` → edite um número em `stack/data/traces/audit.jsonl` → `make auditoria`. Depois, procure o mesmo número no Phoenix: ele mudou lá? Por que o Phoenix não é a prova? (Restaure o arquivo no fim.)
5. **(Opcional, com Docker)** Phoenix:
   ```bash
   docker run -p 6006:6006 arizephoenix/phoenix:latest
   uv sync --extra otlp
   OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:6006 uv run agentready agent ready
   ```
   Abra http://localhost:6006.

## Bloco 5 · Incidente (papéis em `templates/raci.md`)

Ferramentas da triagem: `observe` · `health` · `quarantine` · `lineage --since "<injected_at>"` · `trace last` · `budgets` · `incident detect` · `rollback <CHG>` · `incident resolve` · `incident reveal`.

Entregue o `templates/post-mortem.md` preenchido.

**Trilha stack (Fase 4, opcional):** depois da injeção, `make snapshots` e `make gold-em DECISAO=<trace>` (de `make traces`): que número o agente viu? Resolva com `make incidente ACAO=resolver` e confira em `make snapshots` o marco `restauracao`. Desfaça com `make restaurar PARA=<de>` e refaça. O que o lake **não** desfaz (dica: `make decisoes` e o change log)?
