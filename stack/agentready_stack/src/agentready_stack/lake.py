"""Fase 4 — snapshots do lake com nome: marcos (checkpoints) por etapa da execução.

O DuckLake cria um snapshot a cada commit (cada carga, cada modelo dbt). Os marcos dão nome a eles — "antes de o
agente decidir na terça" — e ficam no ops.duckdb, para uma restauração nunca apagar o próprio índice.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from agentready_stack import warehouse

FONTES = ("ads", "ga4", "meta_capi", "catalogo")
ETAPAS = ("reset", *(f"ingestao.{f}" for f in FONTES), "contratos", "gold_observabilidade", "agente", "restauracao")


def _has(con, table: str) -> bool:
    return bool(con.execute("SELECT 1 FROM information_schema.tables WHERE table_catalog='ops' AND table_name=?",
                            [table]).fetchall())


def ensure(con) -> None:
    if _has(con, "lake_checkpoints"):       # (também numa conexão só de leitura: make snapshots)
        return
    con.execute("""CREATE TABLE IF NOT EXISTS ops.lake_checkpoints (checkpoint_id VARCHAR, dag_run_id VARCHAR,
        etapa VARCHAR, snapshot_id BIGINT, incident_id VARCHAR, lotes VARCHAR[], criado_em TIMESTAMP)""")


def open_incident_id(con) -> str | None:
    """O incidente aberto agora, sem criar nada (o `incidents._ensure` compartilhado cria tabelas no lake)."""
    if not con.execute("SELECT 1 FROM information_schema.tables WHERE table_catalog='ops' AND table_name='incidents'"
                       ).fetchall():
        return None
    r = con.execute("SELECT incident_id FROM ops.incidents WHERE resolved_at IS NULL ORDER BY injected_at DESC LIMIT 1"
                    ).fetchall()
    return r[0][0] if r else None


def last_snapshot_touching(con, table: str) -> int | None:
    """O snapshot mais recente que (re)criou ou escreveu `table` (ex.: o fim do estágio de contrato)."""
    for snap, changes in con.execute(f"SELECT snapshot_id, changes FROM ducklake_snapshots('{warehouse.LAKE}') "
                                     "ORDER BY snapshot_id DESC").fetchall():
        ch = changes or {}
        if table in ch.get("tables_created", []) or table in ch.get("tables_inserted_into", []):
            return snap
    return None


def checkpoint(con, etapa: str, dag_run_id: str | None = None, lotes: list[str] | None = None,
               snapshot_id: int | None = None) -> str:
    if etapa not in ETAPAS:
        raise ValueError(f"etapa inválida para um marco do lake: {etapa}. Use {ETAPAS}")
    ensure(con)
    ck = "CK-" + uuid.uuid4().hex[:8]
    snap, inc = (snapshot_id if snapshot_id is not None else warehouse.lake_snapshot_id(con)), open_incident_id(con)
    con.execute("INSERT INTO ops.lake_checkpoints VALUES (?,?,?,?,?,?,?)",
                [ck, dag_run_id, etapa, snap, inc, list(lotes) if lotes else None, datetime.now()])
    from agentready_stack import telemetry
    with telemetry.span("lake.checkpoint", **{"agentready.etapa": etapa, "agentready.snapshot_id": snap,
                                              "agentready.incident_id": inc, "agentready.checkpoint_id": ck}):
        pass
    return ck


# ----------------------------------------------------------------------------------------------- US2: snapshots

class RestoreRefused(RuntimeError):
    """Restauração recusada (código 2), com o motivo em pt-BR."""


class NotFound(LookupError):
    """Decisão, tabela ou snapshot não encontrado (código 1)."""


def ensure_restores(con) -> None:
    if _has(con, "lake_restores"):
        return
    con.execute("""CREATE TABLE IF NOT EXISTS ops.lake_restores (restore_id VARCHAR, de_snapshot BIGINT,
        para_snapshot BIGINT, novo_snapshot BIGINT, por VARCHAR, motivo VARCHAR, incident_id VARCHAR, feito_em TIMESTAMP)""")


def _snapshots(con) -> list[tuple]:
    return con.execute(f"SELECT snapshot_id, snapshot_time, changes FROM ducklake_snapshots('{warehouse.LAKE}') "
                       "ORDER BY snapshot_id").fetchall()


def snapshots(con, limit: int = 30) -> list[dict]:
    """Os pontos com nome da história do lake (marcos e restaurações), mais novos primeiro, com quantos commits
    o DuckLake fez desde o marco anterior (cada modelo dbt, cada carga = um snapshot)."""
    ensure(con)
    marks = con.execute("SELECT checkpoint_id, etapa, snapshot_id, dag_run_id, incident_id, lotes, criado_em "
                        "FROM ops.lake_checkpoints ORDER BY snapshot_id, criado_em").fetchall()
    all_snaps = {s for s, _t, _c in _snapshots(con)}
    times = {s: t for s, t, _c in _snapshots(con)}
    out, prev = [], None
    for ck, etapa, snap, run, inc, lotes, quando in marks:
        commits = len([s for s in all_snaps if (prev is None or s > prev) and s <= snap])
        out.append({"checkpoint_id": ck, "etapa": etapa, "snapshot_id": snap, "snapshot_time": times.get(snap),
                    "dag_run_id": run, "incident_id": inc, "lotes": lotes or [], "commits_desde_o_anterior": commits,
                    "criado_em": quando})
        prev = snap
    return list(reversed(out))[:limit]


def current_snapshot(con) -> int:
    return warehouse.lake_snapshot_id(con)


def _resolve_target(con, target) -> int:
    t = str(target)
    if t.startswith("CK-"):
        ensure(con)
        r = con.execute("SELECT snapshot_id FROM ops.lake_checkpoints WHERE checkpoint_id = ?", [t]).fetchall()
        if not r:
            raise RestoreRefused(f"marco {t} não existe (veja make snapshots)")
        return r[0][0]
    try:
        return int(t)
    except ValueError:
        raise RestoreRefused(f"destino inválido: {t} (use um número de snapshot ou um marco CK-…)") from None


def _tables_now(con) -> set[str]:
    sch = ", ".join(f"'{s}'" for s in warehouse.DATA_SCHEMAS)
    return {f"{s}.{t}" for s, t in con.execute(
        "SELECT table_schema, table_name FROM information_schema.tables WHERE table_catalog = ? "
        f"AND table_schema IN ({sch}) AND table_type = 'BASE TABLE'", [warehouse.LAKE]).fetchall()}


def _tables_at(con, n: int) -> set[str]:
    """Tabelas das camadas de dados que existiam no snapshot n: todo nome já criado até n (ou existente agora),
    sondado com `AT (VERSION => n)` — a viagem no tempo do DuckLake acha até tabela apagada depois."""
    cands = set(_tables_now(con))
    for s, _t, changes in _snapshots(con):
        if s <= n:
            cands |= {x for x in (changes or {}).get("tables_created", []) if x.split(".")[0] in warehouse.DATA_SCHEMAS}
    at = set()
    for name in cands:
        try:
            con.execute(f"SELECT 1 FROM {name} AT (VERSION => {n}) LIMIT 0")
            at.add(name)
        except Exception:  # noqa: BLE001 — não existia em n
            pass
    return at


def latest_reset_snapshot(con) -> int | None:
    ensure(con)
    r = con.execute("SELECT max(snapshot_id) FROM ops.lake_checkpoints WHERE etapa = 'reset'").fetchone()[0]
    return r


def airflow_active_runs() -> list[str]:
    """Execuções em andamento do DAG (API do Airflow, usuário instrutor). Sem confirmação = recusa (FR-012)."""
    import json as _json
    import os
    import urllib.parse
    import urllib.request
    api = os.environ.get("STACK_AIRFLOW_API", "http://airflow-apiserver:8080")
    pw_file = os.environ.get("STACK_PASSWORDS", "/opt/airflow/config/passwords.json")
    try:
        pw = _json.load(open(pw_file, encoding="utf-8"))["instrutor"]
        req = urllib.request.Request(f"{api}/auth/token", data=_json.dumps({"username": "instrutor", "password": pw}).encode(),
                                     headers={"Content-Type": "application/json"})
        tok = _json.load(urllib.request.urlopen(req, timeout=10))["access_token"]
        q = urllib.parse.urlencode([("state", "running"), ("state", "queued"), ("limit", "20")])
        r = urllib.request.Request(f"{api}/api/v2/dags/aurora_midia_diario/dagRuns?{q}",
                                   headers={"Authorization": f"Bearer {tok}"})
        return [x["dag_run_id"] for x in _json.load(urllib.request.urlopen(r, timeout=10))["dag_runs"]]
    except Exception as e:  # noqa: BLE001
        raise RestoreRefused(f"não consegui confirmar que nenhuma execução está rodando (API do Airflow: {e}); "
                             "restauração recusada por segurança") from e


def restore(con, target, motivo: str, por: str = "instrutor", incident_id: str | None = None) -> dict:
    """Volta as camadas de dados ao snapshot `target` numa transação — que vira UM snapshot novo (a história fica e a
    restauração pode ser desfeita). Nunca toca o ops.duckdb (FR-011). contracts/lake-snapshots.md → "Restore"."""
    from agentready_stack import telemetry
    n = None
    de = current_snapshot(con)
    try:
        n = _resolve_target(con, target)
        active = airflow_active_runs()
        if active:
            raise RestoreRefused(f"há uma execução do DAG em andamento ({active[0]}): um escritor por vez — espere "
                                 "ela terminar e tente de novo")
        known = {s for s, _t, _c in _snapshots(con)}
        if n not in known:
            raise RestoreRefused(f"o snapshot {n} não existe (veja make snapshots)")
        rs = latest_reset_snapshot(con)
        if rs is not None and n < rs:
            raise RestoreRefused(f"o snapshot {n} é de antes do último reset do cenário (snapshot {rs}): o estado vivo "
                                 "das campanhas não bateria com ele")
        if n == de:
            raise RestoreRefused(f"o lake já está no snapshot {n}")
        at, now = _tables_at(con, n), _tables_now(con)
        con.execute("BEGIN")
        try:
            for name in sorted(at):
                con.execute(f"CREATE OR REPLACE TABLE {name} AS SELECT * FROM {name} AT (VERSION => {n})")
            for name in sorted(now - at):
                con.execute(f"DROP TABLE {name}")
            con.execute(f"CALL ducklake_set_commit_message('{warehouse.LAKE}', ?, ?)",
                        [por, f"restauração para o snapshot {n}: {motivo}"])
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise
    except RestoreRefused as e:
        with telemetry.span("lake.restauracao", error=str(e), **{"agentready.de_snapshot": de,
                            "agentready.para_snapshot": n, "agentready.motivo": motivo, "agentready.por": por}):
            pass
        raise
    novo = current_snapshot(con)
    ensure_restores(con)
    rid = "RS-" + uuid.uuid4().hex[:8]
    con.execute("INSERT INTO ops.lake_restores VALUES (?,?,?,?,?,?,?,?)",
                [rid, de, n, novo, por, motivo, incident_id, datetime.now()])
    checkpoint(con, "restauracao")
    with telemetry.span("lake.restauracao", **{"agentready.de_snapshot": de, "agentready.para_snapshot": n,
                                               "agentready.novo_snapshot": novo, "agentready.motivo": motivo,
                                               "agentready.por": por, "agentready.incident_id": incident_id}):
        pass
    return {"restore_id": rid, "de_snapshot": de, "para_snapshot": n, "novo_snapshot": novo, "tabelas": len(at),
            "removidas": sorted(now - at), "desfazer": f"make restaurar PARA={de}"}


def consultar_em(con, tabela: str, em, filtro: str | None = None, limite: int = 20) -> tuple[list[str], list[tuple]]:
    """Leitura de qualquer tabela das camadas de dados num snapshot (número) ou num horário (FR-009)."""
    if "." not in tabela:
        raise NotFound(f"use schema.tabela (ex.: gold.campaign_daily), recebi {tabela}")
    schema = tabela.split(".")[0]
    if schema == "ops" or schema not in warehouse.DATA_SCHEMAS:
        raise RestoreRefused(f"{tabela}: só as camadas de dados têm snapshots ({', '.join(warehouse.DATA_SCHEMAS)}); "
                             "o estado operacional (ops) não viaja no tempo")
    at = f"VERSION => {int(em)}" if str(em).isdigit() else f"TIMESTAMP => TIMESTAMP '{em}'"
    where = f" WHERE {filtro}" if filtro else ""
    try:
        cur = con.execute(f"SELECT * FROM {tabela} AT ({at}){where} LIMIT {int(limite)}")
    except Exception as e:  # noqa: BLE001
        raise NotFound(f"{tabela} não existe nesse ponto do lake ({e})") from e
    return [d[0] for d in cur.description], cur.fetchall()


def decision_run(con, key: str) -> tuple[str, str | None, dict]:
    """trace_id | CHG-… | REQ-… → (trace_id, campanha, resumo da decisão)."""
    info: dict = {}
    trace_id, campaign = key, None
    if key.startswith("CHG-"):
        r = con.execute("SELECT trace_id, campaign_id, action, old_value, new_value, justification FROM ops.change_log "
                        "WHERE change_id = ?", [key]).fetchall()
        if not r:
            raise NotFound(f"alteração {key} não encontrada no change log")
        trace_id, campaign = r[0][0], r[0][1]
        info = {"acao": r[0][2], "de": r[0][3], "para": r[0][4], "justificativa": r[0][5]}
    elif key.startswith("REQ-"):
        r = con.execute("SELECT trace_id, action, params, status FROM ops.approval_queue WHERE request_id = ?",
                        [key]).fetchall()
        if not r:
            raise NotFound(f"pedido {key} não encontrado na fila de aprovação")
        import json as _json
        params = _json.loads(r[0][2]) if isinstance(r[0][2], str) else (r[0][2] or {})
        trace_id, campaign = r[0][0], params.get("campaign_id")
        info = {"acao": r[0][1], "status": r[0][3], "parametros": params}
    return trace_id, campaign, info


def gold_as_of(con, key: str, lookback_days: int = 14) -> dict:
    """A Gold que o agente leu para tomar a decisão (marco `agente` da execução dela) — data-model §5."""
    trace_id, campaign, info = decision_run(con, key)
    r = con.execute("SELECT dag_run_id FROM ops.agent_runs WHERE trace_id = ? ORDER BY started_at DESC LIMIT 1",
                    [trace_id]).fetchall()
    if not r:
        raise NotFound(f"nenhuma execução do agente com o trace {trace_id}")
    run = r[0][0]
    ensure(con)
    ck = con.execute("SELECT checkpoint_id, snapshot_id FROM ops.lake_checkpoints WHERE etapa = 'agente' "
                     "AND dag_run_id IS NOT DISTINCT FROM ? ORDER BY criado_em DESC LIMIT 1", [run]).fetchall()
    if not ck:
        raise NotFound(f"a execução {run} não tem marco `agente` no lake (anterior à Fase 4?)")
    ck_id, snap = ck[0]
    where = "WHERE campaign_id = ?" if campaign else ""
    params = [campaign] if campaign else []
    cur = con.execute(f"""SELECT * FROM gold.campaign_daily AT (VERSION => {snap}) {where}
                          QUALIFY day >= max(day) OVER () - INTERVAL {int(lookback_days) - 1} DAY ORDER BY campaign_id, day""",
                      params)
    cols = [d[0] for d in cur.description]
    return {"decisao": key, "trace_id": trace_id, "dag_run_id": run, "checkpoint_id": ck_id, "snapshot_id": snap,
            "campaign_id": campaign, "decisao_detalhe": info, "colunas": cols, "linhas": cur.fetchall()}
