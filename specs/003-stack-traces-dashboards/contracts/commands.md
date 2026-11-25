# Contract: Commands (Phase 3 delta)

The Phase 1 and 2 commands are unchanged unless listed. All output is pt-BR. `make` targets run from `stack/`.

| Command | New / changed | Behavior | Exit code |
|---|---|---|---|
| `make up` | changed | also starts `otel-collector` and `phoenix`, and prints the Phoenix URL. `check` still requires 8 GB | as before |
| `make auditoria` | **new** | `agentready verify` on the stack's log (`/opt/stack-data/traces/audit.jsonl`): `cadeia íntegra (N registros)` or `registro i: …` | 0 intact · 1 broken |
| `make traces` | **new** | `agentready-stack traces [--limit 10]`: latest runs from `ops.agent_runs`, with business date, incident, agent status and Phoenix link | 0 |
| `make rollback CHG=…` | changed | now `agentready-stack rollback <CHG> --by instrutor`: the shared rollback, wrapped in `humano.rollback` with a link to the original decision trace | as the shared command |
| `make decisoes` | changed | adds the `trace` link column | as before |
| `make test-live` | changed | adds: (a) Phoenix copy == audit copy for a real run; (b) Phoenix stopped mid-run, then restarted, so queued spans arrive and decisions are in the audit log; (c) collector stopped, so the run status is unchanged and `fechamento` warns | 0 all pass |
| `make parity` | changed | report 2.1.0: adds `compared.traces` | 0 only if every section has 0 diffs |
| `make reset` | changed | also clears Phoenix (DB in the shared Postgres volume) and `data/otel-queue`. The message lists traces (Phoenix) | as before |

## `agentready-stack` CLI additions

```text
agentready-stack traces [--limit N]                 → table + last line JSON {"runs": [...]}
agentready-stack rollback <CHG> [--by ACTOR]        → shared rollback inside humano.rollback; JSON {"change_id", "status", "original_trace_url"}
agentready-stack task <any>                         → (all task subcommands) attach TRACEPARENT if present; flush both tracers before exit
```
