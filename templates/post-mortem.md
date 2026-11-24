# Post-mortem sem culpados — <ID do incidente>

> Princípio: perguntamos **"que sistema permitiu?"**, nunca "quem errou?".

| Campo | Valor |
|---|---|
| Incidente | INC-... |
| Severidade | SEV-1 / SEV-2 / SEV-3 |
| Squad / papéis | IC: · Eng. de Dados: · Analista de Negócio: |
| Injetado / iniciado em | |
| Detectado em (TTD) | ___ min |
| Resolvido em (TTR) | ___ min |

## 1. Resumo (3 linhas, linguagem de negócio)

## 2. Impacto
- Decisões do agente tomadas com dado ruim (IDs `CHG-`/`REQ-`):
- Campanhas afetadas e impacto estimado em R$/dia:
- Decisões revertidas (rollback):

## 3. Linha do tempo
| Hora | Evento | Fonte da evidência (comando, trace_id) |
|---|---|---|
| | Deploy/alteração upstream | |
| | Pipeline reprocessou | |
| | Agente decidiu | trace … |
| | Primeiro sinal (pilar: ___) | `agentready observe` |
| | Causa identificada | |
| | Mitigação / resolução | |

## 4. Triagem pelos 5 pilares
| Pilar | Sinal observado | Disparou alerta? |
|---|---|---|
| Frescor | | |
| Volume | | |
| Distribuição | | |
| Esquema | | |
| Linhagem (o que estava a jusante) | | |

## 5. Os 5 Porquês
1. Por que o agente tomou a decisão errada / parou?
2. Por quê?
3. Por quê?
4. Por quê?
5. Por quê? → **causa-raiz sistêmica:**

## 6. O que funcionou (não pule esta seção)
- Ex.: o disjuntor barrou o lote; a pré-condição de frescor impediu ação; o trace mostrou a cadeia causal.

## 7. Ações corretivas
| Ação | Tipo (prevenir / detectar / mitigar) | Onde (contrato, CI/CD, config, processo) | Dono | Prazo |
|---|---|---|---|---|
| | | | | |

## 8. Mudanças propostas no CI/CD
- [ ] Teste de contrato no pipeline do **produtor** (bloqueia deploy com *breaking change*)
- [ ] Nova regra de qualidade no contrato:
- [ ] Monitor promovido a disjuntor (`config/guardrails.yaml`):
- [ ] Alerta com dono e rota de escalonamento:
