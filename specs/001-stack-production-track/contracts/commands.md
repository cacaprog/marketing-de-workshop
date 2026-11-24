# Interface: Stack commands (`stack/Makefile`)

Every command runs from `stack/`. None of them touch the default track (`data/`, `traces/`).

| Command | What it does | Spec |
|---|---|---|
| `make up` | checks host resources (≥ 4 CPU, ≥ 8 GB free RAM, Compose ≥ 2.14); builds the image; starts the services; waits for them to be healthy; prints the UI URL (`http://localhost:8080`) and the users | FR-001, SC-001 |
| `make down` | stops the services and keeps the data | FR-001 |
| `make reset` | `down` plus deleting `stack/data/` (the warehouse, traces and Postgres volume) | FR-001, FR-002 |
| `make run [ARGS='{"reset_scenario": true}']` | triggers `aurora_midia_diario` through the REST API with the given params | US1 |
| `make approvals` | lists pending approval tasks (read-only, for the terminal) | US4 |
| `make parity [SCENARIO=manha\|pos_backfill\|supervisionado\|todos]` | runs `agentready-stack parity` in a one-off container and prints a pt-BR table; exits non-zero on any difference | FR-020, SC-002 |
| `make test` | runs `stack/tests` (pytest) in a one-off container: the DAG integrity test under Airflow's Python, everything else under the agent venv | FR-021 |
| `make contracts-sync` | regenerates `_contracts.generated.yml` with datacontract-cli. The file is never committed; `airflow-init`, the DAG's lint step and the tests also regenerate it | R5 |
| `make logs [SVC=scheduler]` | follows the logs of one service | — |

## `agentready-stack` CLI (inside the agent venv)

| Subcommand | Use |
|---|---|
| `agentready-stack parity --scenario <s> --reference-ts <iso> [--json out.json]` | parity check (writes a JSON matching `parity-report.schema.json`) |
| `agentready-stack doctor` | prints versions (duckdb in each venv, dbt, cosmos, airflow, datacontract) and checks they're compatible |

Exit codes: `0` ok · `1` differences found or check failed · `2` environment error (lock held,
missing service) with a pt-BR message.
