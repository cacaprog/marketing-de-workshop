# Contract: Commands (Phase 4 delta)

Commands from Phases 1–3 are unchanged unless listed. All output is pt-BR. `make` targets run from `stack/`.

| Command | New / changed | Behavior | Exit code |
|---|---|---|---|
| `make up` | changed | also starts `upstream` and `opa`. Prints the sources' URL `http://localhost:8000/docs` (bound to 127.0.0.1). `check` still requires 8 GB | as before |
| `make run ARGS='{…}'` | changed | accepts `falhas_upstream` and `fonte_fora_do_ar` ([dag-interface.md](dag-interface.md)) | as before |
| `make fontes` | **new** | the last load per source from `ops.ingestion_loads` (status, batches new/withdrawn, rows, retries, reason) | 0 |
| `make snapshots` | **new** | `agentready-stack snapshots` | 0 |
| `make gold-em DECISAO=…` | **new** | `agentready-stack gold-em …` | 0 · 1 not found |
| `make consultar-em TABELA=gold.campaign_daily EM=<snapshot\|AAAA-MM-DDTHH:MM> [FILTRO=…]` | **new** | `agentready-stack consultar-em …` ([lake-snapshots.md](lake-snapshots.md#commands)) | 0 · 1 unknown table · 2 `ops` refused |
| `make restaurar PARA=…` | **new** | `agentready-stack restaurar …` | 0 · 2 refused |
| `make politica ACAO='ajustar C01 5200'` | **new** | `agentready-stack politica adjust_campaign_budget C01 5200`. `ACAO='pausar C06'` → `pause_campaign` | 0 allowed · 3 denied · 1 not evaluated |
| `make politica-testes` | **new** | `opa test` on `stack/policy` with `casos.yaml` (verbose) | 0 · 1 |
| `make incidente ACAO=resolver` | changed | source rollback + lake restore + TTD/TTR. It **no longer triggers a DAG run** (the restore already leaves the clean state; the next run re-ingests from the fixed source) ([lake-snapshots.md](lake-snapshots.md#incident-resolve-agentready-stack-incident-resolve)) | 0 · 1 none open · 2 restore refused |
| `make test` | changed | adds `opa test`, the equivalence and fail-closed tests (OPA must be up, like Postgres) and the new suites | 0 all pass |
| `make test-live` | changed | adds: a run fed by the sources; `fonte_fora_do_ar=ga4` (other sources load; ga4 `falhou`; the run finishes); OPA stopped before a run (`agente.executar` fails with the preflight message, 0 executed, no hang; then OPA restarted); `centavos` → resolve → Gold == the pre-incident clean run → undo restore | 0 |
| `make parity` | changed | report 2.2.0 ([parity.md](parity.md)) | 0 only if every section has 0 diffs |
| `make reset` | changed | also drops/recreates the `ducklake` database, and empties `data/lake/`, `data/upstream/` and `data/ops.duckdb` | as before |

## `agentready-stack` CLI additions

```text
agentready-stack task ingest-fonte <ads|ga4|meta_capi|catalogo> --dag-run-id ID  → contracts/ingestion.md
agentready-stack fontes                                                       → last load per source
agentready-stack snapshots [--limit N]
agentready-stack gold-em <trace_id|CHG-…|REQ-…>
agentready-stack consultar-em <schema.tabela> <snapshot|AAAA-MM-DDTHH:MM> [--filtro SQL] [--limite N]
agentready-stack restaurar <snapshot|CK-…> [--motivo T] [--por ATOR]
agentready-stack politica <acao> <campanha> [<novo_orcamento>] [--justificativa T]
agentready-stack incident resolve                                           → changed
```
