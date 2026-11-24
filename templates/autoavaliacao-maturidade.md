# Autoavaliação de maturidade — dados prontos para agentes

Marque, para a **sua empresa**, em que coluna cada dimensão está hoje.

| Dimensão | Human-era (1) | In Transition (2) | Agent-ready (3) | Nota |
|---|---|---|---|---|
| **Contratos** | Esquema implícito; quebra descoberta no dashboard | Testes de qualidade em alguns pipelines | Contratos versionados (ODCS) validados no CI do produtor; quarentena | |
| **Frescor** | "Atualizado diariamente" sem medição | Alertas de atraso em fontes críticas | SLA por fonte, medido pela última carga ok, exposto ao consumidor | |
| **Semântica** | Métricas definidas em cada dashboard | Glossário/documentação de métricas | Métricas como código, compiladas; regras de domínio explícitas | |
| **Acesso do agente** | Acesso direto a tabelas/APIs | APIs internas com autenticação | Capacidades de negócio (MCP) com pré-condições no backend | |
| **Autorização** | No prompt / "o modelo sabe" | Listas de permissões por ferramenta | Guardrails em config versionada; texto nunca autoriza; reversibilidade R0–R3 | |
| **Rastreabilidade** | Logs de aplicação | Logs de chamadas ao LLM | Trace por decisão com fontes, versões e pré-condições; log íntegro e retido | |
| **Autonomia** | Tudo ou nada | Aprovação humana para tudo | Escada por ação (shadow → supervised → guarded → full) | |
| **Observabilidade** | Usuário reclama | Monitores de frescor/volume | 5 pilares + linhagem até a decisão do agente; monitores viram disjuntores | |
| **Cultura** | Caça ao culpado | Post-mortems ocasionais | Post-mortem sem culpados com TTD/TTR e ações no CI/CD | |

**Total:** ____ / 27

## Nossos 2 primeiros passos para segunda-feira
1. **O quê / quem / até quando:**
2. **O quê / quem / até quando:**

*Dica:* escolha a dimensão com nota mais baixa **que esteja no caminho do primeiro caso de uso agêntico** da empresa, não a mais baixa em geral.
