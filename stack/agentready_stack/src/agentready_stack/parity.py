"""Paridade trilha padrão × trilha stack (US2, FR-020): o agente não mudou, só a arquitetura.

Cada trilha roda num SUBPROCESSO com o próprio warehouse temporário (as configurações do
agentready são lidas na importação, então trocar de banco no mesmo processo seria frágil).
As duas partem do mesmo cenário e do mesmo horário de referência e rodam no mesmo dia:
  * padrão: generate -> pipeline.run (Python escrito à mão)
  * stack : generate -> dbt build (contratos + Silver + Gold)
Depois, o MESMO ReadyAgent("rules") decide nas duas. Comparamos Gold, saúde das fontes e decisões,
sem IDs nem horários.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

SCENARIOS = ("manha", "pos_backfill", "supervisionado")          # Fase 1 (relatório 1.0.0)
# Fase 2: um cenário por incidente do Bloco 5 (o lote de ontem do ga4 reenviado com defeito).
INCIDENT_SCENARIOS = ("incidente_centavos", "incidente_renomeacao", "incidente_lote_duplicado", "incidente_feed_parado")
ALL_SCENARIOS = SCENARIOS + INCIDENT_SCENARIOS                     # `make parity SCENARIO=todos`
INCIDENT_PREFIX = "incidente_"
DBT_BIN = os.environ.get("STACK_DBT_BIN", "/opt/venvs/dbt/bin/dbt")


def _dbt_project() -> Path:
    p = Path(os.environ.get("DBT_PROJECT_DIR", "/opt/airflow/dbt/aurora"))
    return p if p.exists() else Path(__file__).resolve().parents[3] / "dbt" / "aurora"


# ----------------------------------------------------------------- um lado (roda no subprocesso)

def _build(track: str, ref: datetime, workdir: str) -> None:
    if track == "default":
        from agentready import pipeline
        pipeline.run(ref)
        return
    from agentready.settings import guardrails

    from agentready_stack.tasks import observability_settings
    proj = _dbt_project()
    env = os.environ | {"DBT_TARGET_PATH": os.path.join(workdir, "target"), "DBT_LOG_PATH": os.path.join(workdir, "logs")}
    obs = observability_settings()
    # Paridade usa SEMPRE a configuração compartilhada do disjuntor (nunca o override por execução).
    vars_ = {"reference_ts": ref.isoformat(),
             "block_on_distribution_anomaly": bool(guardrails()["observability"]["block_on_distribution_anomaly"]),
             "min_history": obs["min_history"], "obs_bands": obs["bands"]}
    vars_ |= json.loads(os.environ.get("STACK_PARITY_EXTRA_VARS") or "{}")   # só testes (deriva de faixa)
    # `dbt build` sem --select: o seletor padrão deixa de fora os testes de VEREDITO (selectors.yml), então
    # uma falha esperada de dados (o incidente) não derruba o build; erro de modelo continua derrubando.
    r = subprocess.run([DBT_BIN, "build", "--project-dir", str(proj), "--profiles-dir", str(proj),
                        "--vars", json.dumps(vars_)], capture_output=True, text=True, env=env)
    if r.returncode != 0:
        raise RuntimeError(f"dbt build falhou na trilha stack:\n{r.stdout[-3000:]}")


def _side(track: str, scenario: str, ref: datetime, workdir: str) -> dict:
    from agentready import autonomy, generate
    from agentready.agent import ReadyAgent
    from agentready.db import connect

    generate.generate(ref)
    _build(track, ref, workdir)
    if scenario == "pos_backfill":
        con = connect()
        t0 = _db_now(con)
        generate.backfill_meta(con)
        _pin_arrivals(con, t0, ref)
        con.close()
        _build(track, ref, workdir)
    if scenario.startswith(INCIDENT_PREFIX):
        from agentready import incidents
        con = connect()
        t0 = _db_now(con)
        incidents.inject(con, scenario.removeprefix(INCIDENT_PREFIX))
        _pin_arrivals(con, t0, ref)
        con.close()
        _build(track, ref, workdir)
    con = connect()
    try:
        if scenario == "supervisionado":
            autonomy.set_override(con, "supervised")
        daily = con.execute("""SELECT campaign_id, CAST(day AS VARCHAR), impressions, clicks, round(spend_brl, 2),
                               orders, round(gross_revenue_brl, 2), round(discount_brl, 2)
                               FROM gold.campaign_daily ORDER BY ALL""").fetchall()
        health = con.execute("""SELECT dataset, "partition", status, age_hours, sla_hours
                                FROM gold.source_health ORDER BY ALL""").fetchall()
        verdicts = _verdicts(track, con)
        rep = ReadyAgent("rules").run(con)
    finally:
        con.close()
    decisions = []
    for s in rep.steps:
        if s.kind == "action":
            r = s.data["result"]
            decisions.append({"campaign_id": r["campaign_id"], "action": r["action"], "status": r["status"],
                              "new_daily_budget_brl": r["params"].get("new_daily_budget_brl"),
                              "failed_checks": sorted(c["id"] for c in r["preconditions"] if not c["passed"])})
        elif s.kind == "refusal":
            decisions.append({"campaign_id": s.text.split(" ·")[0], "action": "refusal", "status": "refused",
                              "new_daily_budget_brl": None, "failed_checks": []})
    return {"campaign_daily": [list(r) for r in daily], "source_health": [list(r) for r in health],
            "decisions": decisions, "observability": verdicts}


def _db_now(con) -> datetime:
    return con.execute("SELECT now()::TIMESTAMP").fetchone()[0]


def _pin_arrivals(con, since: datetime, ref: datetime) -> None:
    """O backfill e a injeção de incidente carimbam as linhas com o relógio (now()). Cada trilha roda num
    momento diferente — e a stack demora mais a chegar nesse passo —, então a idade do feed podia cair em
    lados diferentes do arredondamento de 0,1h (-0.6 × -0.7) sem nenhuma diferença de lógica. O horário de
    chegada é uma ENTRADA do cenário, como o horário de referência: fixamos em ref + 5 min nas duas trilhas."""
    from datetime import timedelta
    con.execute("UPDATE bronze.conversions SET ingested_at = ? WHERE ingested_at >= ?",
                [ref + timedelta(minutes=5), since])


def _verdicts(track: str, con) -> list[list]:
    """[pilar, alvo, status] de cada trilha. Na stack, 'warn' (histórico insuficiente) vale como 'pass':
    é o único mapeamento permitido entre vereditos (pesquisa R7). A trilha padrão é a referência, então
    só ela chama observability.py — o código da stack nunca o chama."""
    if track == "default":
        from agentready import observability
        return sorted([r["pillar"], r["target"], "pass" if r["ok"] else "fail"] for r in observability.report(con))
    return sorted([p, t, "pass" if st == "warn" else st] for p, t, st in
                  con.execute("SELECT pillar, target, status FROM meta.observability_checks").fetchall())


def run_side(track: str, scenario: str, ref: datetime) -> dict:
    """Roda um lado num subprocesso isolado e devolve os resultados normalizados."""
    with tempfile.TemporaryDirectory(prefix=f"paridade-{track}-") as d:
        env = os.environ | {"AGENTREADY_DB": os.path.join(d, "warehouse.duckdb"),
                            "AGENTREADY_TRACES": os.path.join(d, "traces")}
        r = subprocess.run([sys.executable, "-m", "agentready_stack.parity", "_side", track, scenario, ref.isoformat(), d],
                           capture_output=True, text=True, env=env)
        if r.returncode != 0:
            raise RuntimeError(f"lado {track}/{scenario} falhou:\n{r.stderr[-3000:]}")
        return json.loads(r.stdout.strip().splitlines()[-1])


# ----------------------------------------------------------------- comparação (função pura)

def _diff_keyed(a: list, b: list, key_len: int, fields: list[str]) -> tuple[int, list[dict]]:
    ka = {"|".join(map(str, r[:key_len])): r[key_len:] for r in a}
    kb = {"|".join(map(str, r[:key_len])): r[key_len:] for r in b}
    diffs = []
    for k in sorted(set(ka) | set(kb)):
        va, vb = ka.get(k), kb.get(k)
        if va is None or vb is None:
            diffs.append({"key": k, "field": "(linha)", "default_track": va, "stack_track": vb})
            continue
        for f, x, y in zip(fields, va, vb):
            if x != y:
                diffs.append({"key": k, "field": f, "default_track": x, "stack_track": y})
    return len(set(ka) | set(kb)), diffs


def compare(default: dict, stack: dict, scenario: str, ref: datetime) -> dict:
    n_daily, d_daily = _diff_keyed(default["campaign_daily"], stack["campaign_daily"], 2,
                                   ["impressions", "clicks", "spend_brl", "orders", "gross_revenue_brl", "discount_brl"])
    n_health, d_health = _diff_keyed(default["source_health"], stack["source_health"], 2,
                                     ["status", "age_hours", "sla_hours"])
    d_dec = []
    da, db = default["decisions"], stack["decisions"]
    for i in range(max(len(da), len(db))):
        x = da[i] if i < len(da) else None
        y = db[i] if i < len(db) else None
        if x != y:
            key = f"{(x or y)['campaign_id']}|{(x or y)['action']}"
            fields = [f for f in ("status", "new_daily_budget_brl", "failed_checks") if (x or {}).get(f) != (y or {}).get(f)]
            for f in fields or ["(decisão)"]:
                d_dec.append({"key": key, "field": f, "default_track": (x or {}).get(f, x), "stack_track": (y or {}).get(f, y)})
    report = {
        "reference_ts": ref.isoformat(), "business_date": ref.date().isoformat(), "scenario": scenario,
        "compared": {"campaign_daily": {"items": n_daily, "diffs": d_daily},
                     "source_health": {"items": n_health, "diffs": d_health},
                     "decisions": {"items": max(len(da), len(db)), "diffs": d_dec}},
    }
    report["ok"] = not (d_daily or d_health or d_dec)
    return report


def compare_full(default: dict, stack: dict, scenario: str, ref: datetime) -> dict:
    """Relatório 2.0.0 (Fase 2): o de compare() + os vereditos de observabilidade por pilar e alvo.

    compare() continua devolvendo o formato 1.0.0 da Fase 1 (os testes da Fase 1 o validam sem mudança)."""
    report = compare(default, stack, scenario, ref)
    n, diffs = _diff_keyed(default.get("observability", []), stack.get("observability", []), 2, ["status"])
    report["compared"]["observability"] = {"items": n, "diffs": diffs}
    report["ok"] = report["ok"] and not diffs
    return report


def run(scenario: str, reference_ts: datetime | None = None) -> dict:
    if scenario not in ALL_SCENARIOS:
        raise ValueError(f"cenário inválido: {scenario}. Use {ALL_SCENARIOS}")
    ref = (reference_ts or datetime.now()).replace(microsecond=0)
    return compare_full(run_side("default", scenario, ref), run_side("stack", scenario, ref), scenario, ref)


if __name__ == "__main__":  # subprocesso de um lado: python -m agentready_stack.parity _side <track> <cenário> <ref> <dir>
    _, cmd, track, scenario, ref, workdir = sys.argv
    assert cmd == "_side" and track in ("default", "stack")
    print(json.dumps(_side(track, scenario, datetime.fromisoformat(ref), workdir), default=str))
