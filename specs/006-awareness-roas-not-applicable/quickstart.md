# Quickstart: validating 006

Run from the repo root. Contracts: [contracts/semantic-model.md](contracts/semantic-model.md), [contracts/capability-output.md](contracts/capability-output.md).

## V-1 · Offline suite

```bash
uv run pytest -q
```
The existing tests pass unchanged, plus `tests/test_semantic_rules.py` (research R7).

## V-2 · Official results

```bash
uv run agentready setup
uv run agentready ask "ROAS e CAC por campanha nos últimos 14 dias"
```
C05 shows **não se aplica** for ROAS and CAC, with the reason in the note. C03 and C04 show NULL (desconhecido). C01, C02 and C06 match the table in the semantic-model contract.

## V-3 · Capability and MCP tool

```bash
uv run python -c "from agentready import capabilities as c; from agentready.db import connect; import json; print(json.dumps([r for r in c.get_campaign_performance(connect()) if r['campaign_id'] in ('C03','C05')], ensure_ascii=False, default=str, indent=1))"
```
C05 has `roas_status`/`cac_status` = `nao_se_aplica` and the `nao_se_aplica` map; C03 has `desconhecido`.

## V-4 · Workshop demo

```bash
uv run agentready demo 1 --no-pause    # "Gold servida ao agente": C05 roas = não se aplica
uv run agentready demo 2 --no-pause    # official-vs-guessed table: C05 official = não se aplica
uv run agentready demo all --no-pause > /tmp/demo-006.txt
```
Compare the last run with the same command on `main`. Every agent action (⚡ lines) and every refusal (🛑) is identical; only the C05 ROAS/CAC cells and the new note differ (plus ids, timestamps and paths).

## V-5 · Stack

```bash
cd stack && make test && make parity SCENARIO=todos
```
Expect 0 differences in all 7 scenarios. `make test` takes about 26 minutes; don't wrap it in a short timeout.

## V-6 · The measurement that motivated it (after 005 and 006 are both on `main`)

First do task T024: reword 005's `get_campaign_performance` description so it no longer says NULL always means unknown. Without it the measurement is invalid.

```bash
uv run --env-file .env agentready perguntas --brain claude --llm-model haiku --ids roas-c05
```
"com contexto" answers **não se aplica** (before the change: "ROAS 0,60"). Record the date, model and result in `research.md`.
