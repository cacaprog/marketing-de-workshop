"""Paridade trilha padrão × trilha stack (US2, FR-020): o agente não mudou, só a arquitetura.

Cada trilha roda num SUBPROCESSO com o próprio warehouse temporário (as configurações do
agentready são lidas na importação, então trocar de banco no mesmo processo seria frágil).
As duas partem do mesmo cenário e do mesmo horário de referência e rodam no mesmo dia:
  * padrão: generate -> pipeline.run (Python escrito à mão)
  * stack : generate -> dbt build (contratos + Silver + Gold)
Depois, o MESMO ReadyAgent("rules") decide nas duas. Comparamos Gold, saúde das fontes e decisões,
sem IDs nem horários.

Relatórios: compare() = 1.0.0 (Fase 1), compare_full() = 2.0.0 (Fase 2), compare_all() = 2.1.0 (Fase 3:
+ o trace do agente normalizado, contracts/trace-parity.md da spec 003).
"""
from __future__ import annotations

import contextlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
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


INGEST_PY = os.environ.get("STACK_INGEST_PYTHON", "/opt/venvs/ingest/bin/python")
FONTES = ("ads", "ga4", "meta_capi", "catalogo")
BRONZE_TABLES = ("campaigns", "ad_spend", "conversions")


def _upstream_change(track: str, change, ref: datetime) -> None:
    """Backfill ou incidente: na trilha padrão, direto na Bronze; na stack (Fase 4), no armazém das FONTES —
    o "mundo de fora". A Bronze do lake chega pela ingestão (dlt) logo depois (`_stack_ingest`)."""
    if track == "default":
        from agentready.db import connect
        con = connect()
    else:
        from agentready_stack import ingestion
        con = ingestion.store_connect(ingestion.store_path())
    try:
        t0 = _db_now(con)
        change(con)
        _pin_arrivals(con, t0, ref)
    finally:
        con.close()


@contextlib.contextmanager
def _upstream(store: str):
    """As fontes simuladas (só a app pública) num subprocesso, numa porta livre de 127.0.0.1."""
    import socket
    import urllib.request
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "agentready_stack.upstream_app:public_app",
                             "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"],
                            env=os.environ | {"UPSTREAM_STORE_DB": store}, stdout=subprocess.DEVNULL,
                            stderr=subprocess.PIPE, text=True)
    url = f"http://127.0.0.1:{port}"
    try:
        for _ in range(200):
            try:
                urllib.request.urlopen(f"{url}/saude", timeout=1).read()
                break
            except OSError:
                if proc.poll() is not None:
                    raise RuntimeError(f"as fontes simuladas não subiram: {proc.stderr.read()[-2000:]}")
                time.sleep(0.1)
        yield url
    finally:
        proc.terminate()
        proc.wait(timeout=10)


def _stack_ingest(url: str) -> list[list]:
    """As quatro cargas, como as tarefas ingestao.<fonte> do DAG (venv da ingestão, dlt)."""
    out = []
    for f in FONTES:
        r = subprocess.run([INGEST_PY, "-m", "agentready_stack.cli", "task", "ingest-fonte", f, "--dag-run-id", "paridade"],
                           capture_output=True, text=True, env=os.environ | {"UPSTREAM_URL": url})
        if r.returncode != 0:
            raise RuntimeError(f"carga {f} falhou na paridade:\n{r.stderr[-2000:]}")
        res = json.loads(r.stdout.strip().splitlines()[-1])
        out.append([f, res["status"], res.get("motivo")])
    return out


def _bronze(con) -> list[list]:
    """[tabela, lote, linhas, checksum] por lote + [tabela, '(colunas)', n, colunas] — o que a Bronze tem."""
    out = []
    for t in BRONZE_TABLES:
        cols = [r[0] for r in con.execute("SELECT column_name FROM information_schema.columns WHERE "
                                          "table_catalog = current_database() AND table_schema = 'bronze' "
                                          "AND table_name = ? ORDER BY ordinal_position", [t]).fetchall()]
        out.append([t, "(colunas)", len(cols), ",".join(cols)])
        out += [[t, b, n, str(h)] for b, n, h in con.execute(
            f"SELECT batch_id, count(*), bit_xor(hash(x)) FROM bronze.{t} x GROUP BY batch_id ORDER BY ALL").fetchall()]
    return out


def _side(track: str, scenario: str, ref: datetime, workdir: str) -> dict:
    from agentready import autonomy, generate
    from agentready.agent import ReadyAgent

    loads: list[list] = []
    with contextlib.ExitStack() as stack:
        if track == "default":
            from agentready.db import connect
            generate.generate(ref)
            ingest = lambda: None  # noqa: E731 — a trilha padrão escreve a Bronze direto
        else:
            from agentready_stack import ingestion, warehouse
            from agentready_stack.warehouse import connect
            store = ingestion.store_path()
            ingestion.store_generate(store, ref)
            c = warehouse.connect()
            try:
                ingestion.reset_stack(c, ref)
            finally:
                c.close()
            url = stack.enter_context(_upstream(store))
            ingest = lambda: loads.extend(_stack_ingest(url))  # noqa: E731
        ingest()
        _build(track, ref, workdir)
        if scenario == "pos_backfill":
            _upstream_change(track, generate.backfill_meta, ref)
            ingest()
            _build(track, ref, workdir)
        if scenario.startswith(INCIDENT_PREFIX):
            from agentready import incidents
            kind = scenario.removeprefix(INCIDENT_PREFIX)
            _upstream_change(track, lambda con: incidents.inject(con, kind), ref)
            ingest()
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
        bronze = _bronze(con)
        rep = ReadyAgent("rules").run(con)
    finally:
        con.close()
    from agentready import tracing
    tracing.flush()
    trace = normalize_trace(tracing.load(rep.trace_id)) if rep.trace_id else []
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
            "decisions": decisions, "observability": verdicts, "trace": trace, "bronze": bronze, "ingestion": loads}


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
        if track != "default":   # Fase 4: estado operacional no ops.duckdb + lake de catálogo em arquivo + fontes
            env |= {"AGENTREADY_DB": os.path.join(d, "ops.duckdb"),
                    "STACK_LAKE_CATALOG": os.path.join(d, "lake.ducklake"),
                    "STACK_LAKE_DATA": os.path.join(d, "lake") + "/",
                    "STACK_SOURCES_DB": os.path.join(d, "fontes.duckdb")}
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


_IDS = re.compile(r"\b(CHG|REQ)-[0-9a-f]{8}\b")


def _mask(v):
    """IDs aleatórios (uuid) do código compartilhado viram CHG-* / REQ-* (contracts/trace-parity.md)."""
    if isinstance(v, str):
        return _IDS.sub(lambda m: f"{m.group(1)}-*", v)
    if isinstance(v, list):
        return [_mask(x) for x in v]
    if isinstance(v, dict):
        return {k: _mask(x) for k, x in v.items()}
    return v


def normalize_trace(records: list[dict]) -> list[list]:
    """O trace do agente sem IDs nem horários: [chave, status, mensagem, atributos, eventos] por span da
    subárvore de `agent.run`. Chave = caminho de nomes desde agent.run + '#' + campaign_id (ou a ordem
    entre irmãos de mesmo caminho). Função pura (contracts/trace-parity.md)."""
    by_id = {r["span_id"]: r for r in records}
    roots = [r for r in records if r["name"] == "agent.run"]
    if not roots:
        return []
    children: dict[str, list[dict]] = {}
    for r in records:
        if r.get("parent_span_id") in by_id:
            children.setdefault(r["parent_span_id"], []).append(r)
    out: list[list] = []

    def walk(r: dict, path: str) -> None:
        kids = sorted(children.get(r["span_id"], []),
                      key=lambda c: (c["name"], str((c.get("attributes") or {}).get("campaign_id", "")), c["start_time"] or ""))
        seen: dict[str, int] = {}
        for c in kids:
            cpath = f"{path}/{c['name']}"
            cid = (c.get("attributes") or {}).get("campaign_id")
            if cid is None:
                seen[cpath] = seen.get(cpath, 0) + 1
                key = f"{cpath}#{seen[cpath]}"
            else:
                # mesmo nome + mesma campanha mais de uma vez (ex.: agente "crédulo": o ajuste injetado e o corte)
                # vira #C01, #C01#2, ... na ordem de início — nenhuma chave some sem aviso
                base = f"{cpath}#{cid}"
                seen[base] = seen.get(base, 0) + 1
                key = base if seen[base] == 1 else f"{base}#{seen[base]}"
            out.append([key, c["status"], _mask(c.get("status_message")), _mask(c.get("attributes") or {}),
                        _mask([[e["name"], e.get("attributes") or {}] for e in c.get("events") or []])])
            walk(c, key)

    # Uma execução do DAG pode ter mais de um agent.run (a tarefa do agente foi retentada): vale o ÚLTIMO
    # a começar, o da tentativa que terminou. Ordem estável nas duas cópias (log de auditoria e Phoenix).
    root = latest_agent_run(roots)
    out.append(["agent.run#1", root["status"], _mask(root.get("status_message")), _mask(root.get("attributes") or {}),
                _mask([[e["name"], e.get("attributes") or {}] for e in root.get("events") or []])])
    walk(root, "agent.run")
    return sorted(out, key=lambda x: x[0])


def latest_agent_run(roots: list[dict]) -> dict:
    """O agent.run que vale num trace com retentativa: o que começou por último (horários ISO do mesmo formato)."""
    return max(roots, key=lambda r: r.get("start_time") or "")


def diff_traces(a: list[list], b: list[list]) -> tuple[int, list[dict]]:
    ka, kb = {r[0]: r for r in a}, {r[0]: r for r in b}
    diffs = []
    for k in sorted(set(ka) | set(kb)):
        x, y = ka.get(k), kb.get(k)
        if x is None or y is None:
            diffs.append({"key": k, "field": "(span)", "default_track": x and x[0], "stack_track": y and y[0]})
            continue
        for i, f in ((1, "status"), (2, "status_message"), (4, "events")):
            if x[i] != y[i]:
                diffs.append({"key": k, "field": f, "default_track": x[i], "stack_track": y[i]})
        for attr in sorted(set(x[3]) | set(y[3])):
            if x[3].get(attr) != y[3].get(attr):
                diffs.append({"key": k, "field": f"attributes.{attr}", "default_track": x[3].get(attr),
                              "stack_track": y[3].get(attr)})
    return len(set(ka) | set(kb)), diffs


def compare_all(default: dict, stack: dict, scenario: str, ref: datetime) -> dict:
    """Relatório 2.1.0 (Fase 3): o de compare_full() (2.0.0, inalterado) + o trace do agente normalizado."""
    report = compare_full(default, stack, scenario, ref)
    n, diffs = diff_traces(default.get("trace", []), stack.get("trace", []))
    report["compared"]["traces"] = {"items": n, "diffs": diffs}
    report["ok"] = report["ok"] and not diffs
    return report


def run(scenario: str, reference_ts: datetime | None = None) -> dict:
    if scenario not in ALL_SCENARIOS:
        raise ValueError(f"cenário inválido: {scenario}. Use {ALL_SCENARIOS}")
    ref = (reference_ts or datetime.now()).replace(microsecond=0)
    return compare_all(run_side("default", scenario, ref), run_side("stack", scenario, ref), scenario, ref)


if __name__ == "__main__":  # subprocesso de um lado: python -m agentready_stack.parity _side <track> <cenário> <ref> <dir>
    _, cmd, track, scenario, ref, workdir = sys.argv
    assert cmd == "_side" and track in ("default", "stack")
    print(json.dumps(_side(track, scenario, datetime.fromisoformat(ref), workdir), default=str))


def compare_v22(default: dict, stack: dict, scenario: str, ref: datetime) -> dict:
    """Relatório 2.2.0 (Fase 4): o de compare_all() (2.1.0, inalterado) + a Bronze por lote (a da stack chega pelas
    fontes e pelo dlt; a da padrão, pelo gerador) + o status de cada carga da stack (contracts/parity.md)."""
    report = compare_all(default, stack, scenario, ref)
    n, diffs = _diff_keyed(default.get("bronze", []), stack.get("bronze", []), 2, ["rows", "checksum"])
    report["compared"]["bronze"] = {"items": n, "diffs": diffs}
    loads = stack.get("ingestion", [])
    ing = [{"key": f, "field": "status", "default_track": None, "stack_track": f"{st}: {mot}" if mot else st}
           for f, st, mot in loads if st not in ("carregado", "sem_dados_novos")]
    report["compared"]["ingestion"] = {"items": len(loads), "diffs": ing}
    report["ok"] = report["ok"] and not diffs and not ing
    return report
