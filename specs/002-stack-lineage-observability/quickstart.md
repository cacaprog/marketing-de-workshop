# Quickstart: validating Stack Track Phase 2

Run everything from `stack/`. These steps assume Phase 1's quickstart already works. Interfaces:
[dag-interface.md](contracts/dag-interface.md), [commands.md](contracts/commands.md),
[lineage-events.md](contracts/lineage-events.md). Tables: [data-model.md](data-model.md).

## Prerequisites

- Docker Compose ≥ 2.14, **≥ 4 CPU, ≥ 10 GB free RAM** (`make check`).
- A clean state: `make reset && make up`. `make up` prints three URLs: Airflow `:8080`, lineage `:3000`,
  report `:8090`.

## V-P2-0 — Upgrade gate (US5, FR-019): run **before** any other Phase 2 change

1. `make doctor` shows `dbt-core 1.12.x`, `dbt-duckdb 1.11.1`, `duckdb 2.0.1` in the dbt and agent venvs.
2. `make test`: every Phase 1 stack test passes. `uv run pytest -q` (repo root): the default suite passes.
3. `make parity SCENARIO=todos` (still the 3 Phase 1 scenarios at this point): **0 differences**.

**Expected:** all three pass. Only then add Elementary and lineage.

## V-P2-1 — Clean morning (US1 AS1)

`make run ARGS='{"reset_scenario": true}'`, then `make observe`.
**Expected:** each pillar's verdict matches `agentready observe` on the default track for the same scenario. The
Meta feed is stale on both. `observabilidade.resumo` fails only for pillars the default track also flags.

## V-P2-2 — `centavos`, breaker off (US1 AS2, FR-006, SC-001)

`make run ARGS='{"incident": "centavos"}'`.
**Expected:** `contratos.alerta_qualidade` is **green** (the contract passes). `observabilidade.resumo` and
`observabilidade.testes` are **red**, with `distribuição | conversions/ga4.order_value_brl | False | ticket médio do último lote …-redelivery:
R$ ~20.000 vs mediana R$ ~200 (~100x)`. The agent still ran. The report at `:8090` shows the failed test with its
history.

## V-P2-3 — Lineage and blast radius (US3, SC-005)

Open `http://localhost:3000` → namespace `aurora`, and time how long the steps take.
**Expected:** going `bronze.conversions` → contract models → `silver.conversions` → `gold.campaign_daily` →
`agente.executar` takes under 2 min. The agent run shows the `agentready_trace` facet. `make decisoes
DESDE=<injection time from make incidente ACAO=listar>` lists the decisions with that trace id.

## V-P2-4 — Breaker on via per-run override (US1 AS3, FR-005, SC-002)

`make incidente ACAO=resolver` (this triggers a clean run), then
`make run ARGS='{"incident": "centavos", "disjuntor_distribuicao": "ligado"}'`.
**Expected:** the ingest log says `disjuntor de distribuição: ligado (override desta execução)`.
`meta.batch_status` has the redelivered batch `barred`, `barred_by='distribuicao'`. Its rows are in
`quarantine.conversions` with the distribution reason. **0 rows** from it in Silver/Gold.
`contratos.alerta_qualidade` is red (a new barred batch). The distribution verdict is green (post-breaker Silver).
The next `make run` with no params reads the shared setting again (off).

## V-P2-5 — Other incidents (US1 AS4, FR-007)

For `renomeacao`, `lote_duplicado` and `feed_parado`: `make incidente ACAO=resolver` between each, then
`make run ARGS='{"incident": "<kind>"}'`.
**Expected:** the failing pillar is `esquema`, `volume` and `frescor` respectively, matching the default track.

## V-P2-6 — Extended parity (US2, SC-003)

`make parity SCENARIO=todos`.
**Expected:** 7 scenarios, **0 differences**, including `observability`.

## V-P2-7 — Failure behavior (edge cases, FR-013)

1. `docker compose stop marquez-api`, then `make run`. **Expected:** the same task states as with Marquez up; the
   closing log says `linhagem indisponível: …`. `docker compose start marquez-api`.
2. `make reset && make up`, then remove most of the history by hand (the test fixture
   `short_history` does this), then run. **Expected:** volume and distribution show `warn`
   (`histórico insuficiente`); nothing is blocked.

## V-P2-8 — Block 5 runbook, dry run (US4, SC-006)

Someone who hasn't seen the incident follows only the README's Block 5 section with `incident: aleatorio`.
**Expected:** they name the failing pillar and the affected decisions in under 10 min; TTD/TTR come from
`make incidente ACAO=resolver`.

## V-P2-9 — Timing and resources (SC-007)

Record in the README: `make up` time, the first full run up to the approval pause (target ≤ 5 min), peak RAM
(`docker stats`), and clean checkout → finished run (target ≤ 15 min).

## Automated tests (FR-016)

`make test` runs the new tests listed in plan.md's test matrix, alongside Phase 1's.
