# Interface: Approval request (Human-in-the-loop form)

One mapped `HITLOperator` task per entry in `ops.approval_queue` created by the current run.

## Operator configuration

| Field | Value |
|---|---|
| `subject` | `"[{action}] {campaign_id} · {campaign_name}"` (pt-BR) |
| `options` | `["Aprovar", "Rejeitar"]` |
| `defaults` | `["Rejeitar"]`, applied only on timeout; the outcome is recorded as **expired**, not rejected |
| `multiple` | `False` |
| `response_timeout` | `stack/config/stack.yaml → approvals.response_timeout` (default `20h`, so an unanswered request expires before the next 07:00 run; demos use e.g. `10m`) |
| `assigned_users` | `[{"id": "aprovadora", "name": "aprovadora"}]` from `stack.yaml → approvals.approvers` (entry shape to be confirmed against the installed provider, see research R4) |
| `params` | `{"comentario": Param("", type="string")}`: an optional free-text note, recorded with the decision |

## Body (Markdown, pt-BR), rendered from the request

```markdown
**Ação proposta pelo agente:** ajustar orçamento diário
**Campanha:** C02 · Google Search - Genérico
**Atual → proposto:** R$ 5.000 → R$ 5.500 (+10%)
**Justificativa do agente:** maior ROAS líquido 14d com dados frescos (2.81)
**Por que precisa de você:** variação de +10% … / pausar campanha é R2

| Pré-condição | Resultado | Detalhe |
|---|---|---|
| dados_frescos | ✅ | conversões via ga4: fresh (3.0h) |
| teto_do_portfolio | ✅ | … |

Trace: `<trace_id>` · Pedido: `REQ-xxxx`
> A aprovação NÃO dispensa as pré-condições: elas serão verificadas de novo no estado vivo.
```

## Decision → outcome (applied by `aprovacao.aplicar`)

| HITL payload | Outcome | Effect on `ops.approval_queue` | Effect on `ops.campaigns` |
|---|---|---|---|
| `chosen_options=["Aprovar"]`, user present | `executed` or `rejected_live_recheck` | `approved`, `decided_by=<user>` | applied through `decide_approval` (live re-check) |
| `chosen_options=["Rejeitar"]`, user present | `rejected` | `rejected`, `decided_by=<user>` | none |
| user empty, or `responded_at ≥ timeout_datetime` | `expired` | `expired`, `decided_by="sistema:timeout"` | none |
| task failed (e.g., `HITLTimeoutError` if defaults were removed) | `expired` | same as above | none |
