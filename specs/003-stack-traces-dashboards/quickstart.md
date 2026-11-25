# Quickstart: Validating Stack Track Phase 3

Run from `stack/`. Prerequisites: Phases 1–2 working (`make up`, `make run`), ≥ 4 CPUs, ≥ 8 GB free RAM. Each
scenario lists the command and the expected outcome. Span names: [contracts/span-catalog.md](contracts/span-catalog.md).
Links: [contracts/trace-links.md](contracts/trace-links.md).

| ID | Scenario | Do | Expect |
|---|---|---|---|
| **V-P3-0** | Spike (before any task code) | Add only `otel-collector` + `phoenix` + the env block. `make up`, `make run ARGS='{"autonomy_override": "shadow"}'` | Phoenix at :6006 lists project `aurora`. The run's `worker.*` spans arrive during the run and `dag_run.*` at the end. Record: how Phoenix lists a trace whose root hasn't arrived (R5), the `OTEL_EXPORTER_OTLP_TIMEOUT` unit, the exporter name in 0.166.0. If Phoenix 22.0.1 misbehaves, switch to 21.3.0 and record why |
| **V-P3-1** | Default track untouched | `uv run pytest -q` at the repo root | passes, no test changed (FR-016) |
| **V-P3-2** | Stack unit tests | `make test` | all pass, including the new `test_telemetry*.py`, `test_trace_parity.py`, `test_rollback_link.py` |
| **V-P3-3** | Auditor interrogation (US1, SC-001) | `make run` (no incident), then open the link from the `agente.executar` log | one trace: `dag_run` → `worker.agente.executar` → `agent.run` subtree. `tool.adjust_campaign_budget` for C01 shows the metric, the semantic/guardrail versions, the preconditions and the autonomy level. The C03/C04 refusal is `sem_dados` in `agent.reasoning`, with the stale Meta feed in `tool.get_data_health` → `data.stale_sources`. Time a newcomer: ≤ 5 min for the 3 questions |
| **V-P3-4** | Duplicate skip (US1 AS4) | `make run` again with the same data | the log says `Sem trace: já decidido…`. `agente.resultado` shows `skipped_duplicate`, and there is no new `agent.run` |
| **V-P3-5** | Run ↔ decision ↔ blocked batch (US2 AS1–AS2) | `make run ARGS='{"incident": "lote_duplicado"}'` | in the run's trace, `contratos.lote` for the ga4 batch is ERROR (`lote … barrado: quarentena …`) with the counts, and the agent subtree is in the same tree (0–1 clicks, SC-003) |
| **V-P3-6** | `centavos` with breaker off (US2 AS3) | `make run ARGS='{"incident": "centavos"}'` | `observabilidade.veredito` distribution/ga4 is ERROR with the ratio, and `agent.run` in the same trace still decided |
| **V-P3-7** | Approval link (US2 AS4) | `make run ARGS='{"autonomy_override": "supervised"}'`, open the request in Airflow as `aprovadora` | the form has the Phoenix link (1 click). After approving, `human.approval` appears in the same trace. A request left to expire shows `human.approval_expired` |
| **V-P3-8** | Rollback link | `make decisoes`, then `make rollback CHG=<id>` | the output prints `Decisão original: <link>`. Phoenix has a `humano.rollback` trace with a link to the original `agent.run`, and the audit log has `human.rollback` |
| **V-P3-9** | Tamper evidence (US3, SC-006) | `make auditoria` → edit one number in `data/traces/audit.jsonl` → `make auditoria` | `cadeia íntegra (N registros)`, then `registro i: conteúdo alterado (<span>)` with exit 1. Restore the file afterwards (or `make reset`) |
| **V-P3-10** | Outages (US3 AS3, SC-005) | `make test-live` | Phoenix stopped mid-run: the run status is unchanged, and the spans arrive after restart (queue). Collector stopped: the run status is unchanged, `fechamento` warns in pt-BR, and every executed decision is in `make auditoria`'s log |
| **V-P3-11** | Trace parity (SC-002) | `make parity` (all 7 scenarios) | `compared.traces.diffs` is empty everywhere. The report validates against schema 2.1.0 |
| **V-P3-12** | Resources (SC-007) | `docker stats --no-stream` at the run's peak | the total stays within the 8 GB minimum. Record the number in the guide |
| **V-P3-13** | Offline (FR-017) | `docker compose up` with the network disconnected after images are pulled | Phoenix UI loads (no external fonts) and the run traces normally |
| **V-P3-14** | Guide and script (US4) | read `stack/README.md` and `docs/01-roteiro-do-instrutor.md` | replacement map rows, gaps (research R11), roadmap Phase 3 ✅ and Grafana removed with reason, the Block 4 stack runbook, the Phoenix URL |
| **V-P3-15** | Persistence and search (FR-003) | `make down && make up`, then filter Phoenix spans by `agentready.business_date` | earlier runs are still there and the filter finds them |
