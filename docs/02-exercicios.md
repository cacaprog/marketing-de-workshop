# Exercícios dos participantes

Trabalhe em dupla (um perfil técnico + um de negócio). Para voltar ao estado inicial a qualquer momento: `uv run agentready setup`.
Todos os comandos abaixo assumem o prefixo `uv run`.

## Bloco 1 · Contratos e quarentena

1. **Leia o contrato.** Abra `contracts/conversions.odcs.yaml`. Quais regras pegaram cada motivo de `agentready quarantine`?
2. **Faixa plausível.** Adicione `maximum: 5000` em `logicalTypeOptions` de `order_value_brl`. Rode `agentready pipeline`. Algo novo entrou em quarentena? *Guarde esta regra: ela vai importar no Bloco 5.*
3. **Sensibilidade do disjuntor.** Mude `maxQuarantineRate` para `0.005`. Quantos lotes são barrados agora (`agentready health`)? Qual o custo de um disjuntor sensível demais?
4. **(Negócio) O SLA é uma decisão de negócio.** Mude o `latency` de conversões de 24 para 96 horas e rode `agentready pipeline` e `agentready agent ready`. O que o agente fez com a Meta? Quem na empresa deveria ser dono desse número?
5. Desfaça as mudanças 3 e 4 (`git checkout contracts/` ou edite de volta) e rode `agentready setup`.

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

## Bloco 4 · Rastreabilidade e autonomia

1. **Interrogatório do auditor.** Com `agentready trace last` e o HTML em `traces/`, respondam:
   - Por que o orçamento do C01 subiu? Com base em qual número?
   - Qual versão do modelo semântico e dos guardrails estava valendo?
   - Por que nada foi feito com C03?
2. `agentready autonomy shadow` → `agentready agent ready` → `agentready budgets`. Algo mudou? Depois `agentready autonomy clear`.
3. `agentready approvals` → `agentready approve <REQ>`. Antes de aprovar, trave a campanha (exercício 3.3). O que acontece?
4. **Adulteração.** Edite um número em `traces/audit.jsonl` e rode `agentready verify`.
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
