# Contract: Business question set (`config/perguntas.yaml`)

Shared business configuration (versioned like `guardrails.yaml`). Text in pt-BR. Official answers are **rules**, resolved at run time against the regenerated scenario; the file holds no expected numbers.

```yaml
version: 1.0.0
tolerancia_relativa: 0.02
perguntas:
  - id: receita-c01
    texto: "Qual foi a receita líquida da campanha Google Search - Marca (C01) nos últimos 7 dias?"
    mostra: "Receita é sempre líquida; linhas duplicadas e inválidas ficam na quarentena."
    resposta_oficial: {tipo: metrica, metrica: net_revenue, campanha: C01, janela_dias: 7}
  - id: roas-c02
    texto: "Qual o ROAS da campanha Google Search - Genérico (C02) nos últimos 14 dias?"
    mostra: "ROAS é receita líquida ÷ investimento, somados no período."
    resposta_oficial: {tipo: metrica, metrica: roas, campanha: C02, janela_dias: 14}
  - id: cac-c06
    texto: "Qual o CAC da campanha YouTube - Vídeo Conversão (C06) nos últimos 14 dias?"
    mostra: "Pedidos inválidos não contam."
    resposta_oficial: {tipo: metrica, metrica: cac, campanha: C06, janela_dias: 14}
  - id: receita-c03
    texto: "Qual foi a receita líquida da campanha Meta - Prospecção (C03) nos últimos 7 dias?"
    mostra: "Dado atrasado não é zero nem é completo: é desconhecido."
    resposta_oficial: {tipo: desconhecido_se_atrasado, campanha: C03}
  - id: roas-c05
    texto: "Qual o ROAS da campanha TikTok - Awareness (C05)?"
    mostra: "Campanhas de awareness são avaliadas por alcance, nunca por ROAS."
    resposta_oficial: {tipo: nao_se_aplica, regra: awareness_nao_usa_roas, campanha: C05}
  - id: abaixo-do-piso
    texto: "Quais campanhas estão abaixo do ROAS mínimo de 1,0 nos últimos 14 dias?"
    mostra: "Só campanhas de conversão, e só com dados atuais."
    resposta_oficial: {tipo: campanhas, criterio: roas_abaixo_do_piso, janela_dias: 14}
  - id: sem-dados-atuais
    texto: "Os dados de conversão estão atualizados? Quais campanhas estão sem dados atuais?"
    mostra: "O frescor é medido por feed, contra o SLA do contrato."
    resposta_oficial: {tipo: campanhas, criterio: fonte_atrasada}
  - id: investimento-total
    texto: "Quanto investimos em mídia no total nos últimos 14 dias?"
    mostra: "Controle: o dado de investimento está limpo, e as duas respostas podem acertar."
    resposta_oficial: {tipo: metrica, metrica: spend, campanha: null, janela_dias: 14}
```

## Resolution rules

| `tipo` | Official status | Official value | Source |
|---|---|---|---|
| `metrica` | `valor` (or `desconhecido` if the metric comes back NULL) | the metric for the campaign (or the total when `campanha: null`) over the window | semantic layer (`semantic.query`) |
| `desconhecido_se_atrasado` | `desconhecido` when the campaign's conversion source is stale; otherwise resolves as `metrica` net_revenue | — | `gold.source_health` |
| `nao_se_aplica` | `nao_se_aplica` | — | `domain_model.rules` in the semantic model |
| `campanhas` | `valor` | a set of campaign ids | `roas_abaixo_do_piso`: conversion campaigns with fresh data and official ROAS < `roas_floor`; `fonte_atrasada`: campaigns whose conversion source is stale |

## Verdicts (FR-030)

| Verdict | When |
|---|---|
| certa | status matches and (number within `tolerancia_relativa`, or campaign set equal) |
| desconhecido correto | official `desconhecido` and the answer's status is `desconhecido` |
| inventou número | official `desconhecido` or `nao_se_aplica`, and the answer is `valor` with a number |
| errada | any other mismatch |
| sem resposta | the model ended without calling `responder` |
| falhou | server error, timeout or invalid tool calls |

A file that fails validation (unknown metric, campaign or criterion) stops the command with a pt-BR message naming the question id.
