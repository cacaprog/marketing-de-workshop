# Matriz RACI — Simulação de incidente (Bloco 5)

R = executa · A = responde pelo resultado · C = consultado · I = informado

| Atividade | Incident Commander | Engenheiro(a) de Dados | Analista de Negócio |
|---|---|---|---|
| Declarar o incidente e a severidade | **A/R** | C | C |
| Injetar o incidente (sem olhar o tipo) | **R** | I | I |
| Rodar os 5 pilares (`observe`, `health`, `quarantine`) | I | **A/R** | I |
| Linhagem e impacto a jusante (`lineage --since`) | C | **A/R** | C |
| Ler o trace das decisões do agente (`trace last`) | C | R | **A/R** |
| Estimar impacto em R$ e campanhas afetadas | I | C | **A/R** |
| Decidir pausar o agente (`autonomy shadow`) | **A** | R | C |
| Registrar detecção (`incident detect`) | **A/R** | I | I |
| Reverter decisões contaminadas (`rollback`) | A | **R** | C |
| Resolver (`incident resolve`) e medir TTR | **A** | R | I |
| Conduzir os 5 Porquês | **A/R** | C | C |
| Redigir o post-mortem | A | R | **R** |
| Comunicar stakeholders (status a cada 15 min) | **A/R** | I | C |

**Regras do jogo:** o IC não investiga, ele coordena; ninguém executa rollback sem o IC aprovar; toda afirmação precisa de evidência (comando ou trace_id).
