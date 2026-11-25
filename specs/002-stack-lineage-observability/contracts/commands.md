# Interface: stack commands, Phase 2 changes

This extends [Phase 1's commands](../../001-stack-production-track/contracts/commands.md). Every command runs from `stack/`.

| Command | What it does | Spec |
|---|---|---|
| `make check` | the minimum is now **≥ 4 CPU and ≥ 10 GB free RAM** | FR-022 |
| `make up` | also starts `marquez-api`, `marquez-web` and `relatorio`; prints **3 URLs**: Airflow `:8080`, lineage `:3000`, observability report `:8090` | FR-011, FR-004 |
| `make reset` | also wipes the `marquez` database (it's in the same Postgres volume) and `data/elementary/` | US3 AS4 |
| `make run ARGS='{"incident":"centavos","disjuntor_distribuicao":"ligado"}'` | new param (see dag-interface.md) | FR-005 |
| `make observe` ★ | prints the latest run's five-pillar table from `meta.observability_checks` (the same as the `resumo` task) | FR-004 |
| `make incidente ACAO=detectar\|resolver\|revelar\|listar` ★ | Block 5 lifecycle on the stack warehouse. `resolver` restores Bronze and **triggers a DAG run** (never the default pipeline) | FR-022, research R8 |
| `make decisoes DESDE=<iso>` ★ | agent decisions (executed and queued) since T, with trace id and a Marquez link to the agent run | FR-012 |
| `make parity SCENARIO=…` | scenarios now include `incidente_centavos\|incidente_renomeacao\|incidente_lote_duplicado\|incidente_feed_parado`; `todos` = all 7 | FR-015, SC-003 |
| `make doctor` | also prints elementary (package and CLI), the openlineage provider, and Marquez API health | — |

## `agentready-stack` CLI (added subcommands)

| Subcommand | Use |
|---|---|
| `agentready-stack task observe` | the `resumo` stage; last stdout line is the JSON verdict list; exit 1 if any verdict is `fail` |
| `agentready-stack incident detect\|resolve\|reveal\|list` | the shared `incidents.*` functions; `resolve` does **not** run any pipeline (the Makefile triggers the DAG) |
| `agentready-stack decisions --since <iso> [--json]` | changes + queued requests since T, with trace ids |
| `agentready-stack lineage-check` | `GET /api/v1/namespaces/aurora` on Marquez; exit 0 always; prints a warning when it's down |

Exit codes are unchanged (`0` ok · `1` check failed or differences found · `2` environment error).
