# Quickstart & Validation: Stack Track (Phase 1)

This guide proves the feature works end to end. Each step links to the spec item it validates.
Interfaces: [commands](contracts/commands.md) · [DAG](contracts/dag-interface.md) ·
[approval form](contracts/approval-request.md) · data shapes: [data-model](data-model.md).

## Prerequisites

- Docker Engine with Compose ≥ 2.14; ≥ 4 CPU and ≥ 8 GB of free RAM.
- This repository checked out. The default track does **not** need to be set up.
- `cp stack/config/passwords.example.json stack/config/passwords.json`

## V1 — Start from a clean checkout (US1 · FR-001 · SC-001)

```bash
cd stack && make up
```

Expected: every service is `healthy` and the terminal prints the UI address and the users
`instrutor` / `aprovadora`. Timing: up to 15 minutes, not counting image downloads.

## V2 — The morning run, end to end (US1, US3 · FR-004/005/010–013)

```bash
make run ARGS='{"reset_scenario": true}'
```

In the UI (log in as `instrutor`), open `aurora_midia_diario`. Expected:

- The stages appear in this order: `ingestao` → `contratos` → `gold` → `agente` → `aprovacao` → `fechamento`.
- `contratos.alerta_qualidade` is **red** only on the first run after a reset (all blocked batches are new); everything else is green. The next run is green.
- The `agente.executar` log shows the narrated report, which includes refusals for C03/C04
  ("Não possuo dados atuais de conversão…") because `meta_capi` is stale.
- In the warehouse, `quarantine.conversions` has the dirty rows, the old ga4 batch is `barred`
  in `meta.batch_status`, and `gold.source_health` shows `conversions/meta_capi = stale`.

## V3 — Approve, reject and expire (US4 · FR-016–019 · SC-006)

```bash
make run ARGS='{"autonomy_override": "supervised"}'
```

Log in as `aprovadora` and open **Required actions** (the HITL inbox). Expected: one form per
proposed action, showing the current and proposed values, the justification and the checks table.

- Approve one: `aprovacao.aplicar` → `executed`, `ops.change_log` has `actor=agent+aprovadora`,
  and `make rollback CHG=<CHG>` undoes it on the stack warehouse.
- Reject one: the outcome is `rejected` and `ops.campaigns` is unchanged.
- Expiry: with `approvals.response_timeout: 2m` in `stack/config/stack.yaml`, leave one alone.
  The outcome is `expired`, `decided_by=sistema:timeout`, and nothing changes.

## V4 — Idempotent re-run (FR-006 · SC-007)

Trigger `make run` again with no params. Expected: `agente.executar` ends with
`skipped_duplicate` ("já decidido para estes dados"), and `ops.change_log` gets 0 new rows.

## V5 — Parity with the default track (US2 · FR-020 · SC-002)

```bash
make parity SCENARIO=todos
```

Expected: three tables (manha, pos_backfill, supervisionado), each with `0 diferenças`, and exit
code 0.

## V6 — Prompt injection is still refused (edge case)

```bash
make run ARGS='{"gullible": true}'
```

Expected: the agent "believes" the C06 briefing and asks for R$ 35 mil/dia; the backend rejects
it on `variacao_maxima` and `teto_do_portfolio`, exactly as on the default track.

## V7 — The documented gap: centavos (US5 · FR-025)

```bash
make run ARGS='{"incident": "centavos"}'
```

Expected: the contracts **pass** (no new quarantine for that batch). This is the Phase 1 gap
named in `stack/README.md`, which Phase 2 (anomaly observability) closes.

## V8 — Automated tests (FR-021/022 · SC-003/004)

```bash
make test                  # stack track: one test per Phase 1 promise
cd .. && uv sync --extra dev && uv run pytest -q  # default track: unchanged, all pass (a fresh clone needs the dev extra)
```

## V9 — The default track is untouched (edge case)

After V1–V8, run `git status` at the repo root. Expected: nothing changed outside `stack/`
except the files listed in tasks.md T058 (`capabilities.py`, `contracts.py`, `db.py`, `agent.py`, the ODCS 3.1
migration of `contracts/`, two docs, the root README and `.gitignore`). `data/warehouse.duckdb` has the same modification time as before.

## Teardown

```bash
make down      # keep the data
make reset     # wipe the stack's data
```
