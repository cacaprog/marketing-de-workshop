# Contract: Trace Links

**Builder** (one place, `agentready_stack/telemetry.py`):

- `trace_url(trace_id) → http://localhost:${PHOENIX_PORT:-6006}/redirects/traces/<trace_id>`
- `span_url(span_id) → http://localhost:${PHOENIX_PORT:-6006}/redirects/spans/<span_id>`

`trace_url(None)` returns `None`. Callers print the pt-BR reason instead of a broken link.

| Where | What the user sees (pt-BR) | Spec |
|---|---|---|
| Approval form body (`approvals.to_hitl_kwargs`) | `[Abrir o raciocínio do agente no Phoenix](<trace_url>)` under the existing `Trace:` line | FR-007, SC-003 |
| `agente.executar` task log | `Trace desta execução no Phoenix: <trace_url>`, or `Sem trace: já decidido para estes dados (execução pulada).` | FR-007 |
| `agente.executar` XCom | `"trace_url": "<url>" \| null` (additive key; the Phase 1/2 keys are unchanged) | FR-007 |
| `fechamento` summary | `Traces: no Phoenix (<trace_url>)`, or the R6 warning | FR-012 |
| `make decisoes` | one more column, `trace` (link) | FR-007 |
| `make traces` | latest runs: `execução · data de negócio · incidente · agente · link` | FR-003 |
| `humano.rollback` span and `make rollback` output | `Decisão original: <trace_url>` | FR-008 |
| `make up` banner | `Traces (Phoenix) ............. http://localhost:${PHOENIX_PORT}` | FR-019 |
