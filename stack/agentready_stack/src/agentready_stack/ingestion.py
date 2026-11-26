"""Fase 4 — da fonte à Bronze.

`run_source` (US1): para cada fonte simulada, compara o manifesto de lotes com a última carga, roda o dlt (fonte
REST API declarativa: paginação, novas tentativas, dicas de coluna) gravando Parquet, e faz o commit em
`warehouse.bronze_raw` + Bronze numa transação do DuckDB 2.0.1 (um snapshot do lake por carga). Cada tentativa
vira uma linha em `ops.ingestion_loads` e um span `ingestao.carga`. Nunca conserta dado de negócio.

`bridge_load` (fundação): cópia de referência do armazém das fontes para o lake — usada nos testes para provar
que a carga pelo dlt dá exatamente a mesma Bronze.
"""
from __future__ import annotations

import glob
import json
import os
import tempfile
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from unittest import mock

import duckdb

import agentready.db as _db
from agentready import generate, incidents

# Capturado na importação: nos testes, o conftest troca `agentready.db.connect` pela conexão da stack, mas o
# armazém das fontes é um DuckDB comum, aberto pelo conector original.
_SHARED_CONNECT = _db.connect

# Tabelas de bronze_raw por tabela da Bronze (as conversões chegam de duas fontes: ga4 e Meta).
RAW = {"ad_spend": ("ad_spend",), "campaigns": ("campaigns",),
       "conversions": ("conversions__ga4", "conversions__meta_capi")}
DLT_COLUMNS = ("_dlt_load_id", "_dlt_id")


def store_path() -> str:
    return os.environ.get("STACK_SOURCES_DB", "/opt/stack-data/upstream/fontes.duckdb")


@contextmanager
def shared_store(path: str):
    """Faz o código compartilhado (gerador, incidentes) escrever no armazém das fontes, não no lake."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with mock.patch.object(_db, "DB_PATH", Path(path)), mock.patch.object(generate, "connect", _SHARED_CONNECT):
        yield


def store_generate(path: str, now: datetime | None = None) -> dict:
    with shared_store(path):
        return generate.generate(now)


def store_connect(path: str) -> duckdb.DuckDBPyConnection:
    with shared_store(path):
        return _SHARED_CONNECT()


def _columns(con, schema: str, table: str) -> list[str]:
    return [r[0] for r in con.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_catalog=current_database() "
        "AND table_schema=? AND table_name=? ORDER BY ordinal_position", [schema, table]).fetchall()]


def _raw_select(con, raw: str) -> str:
    dlt = [c for c in DLT_COLUMNS if c in _columns(con, "bronze_raw", raw)]
    return f"SELECT * {'EXCLUDE (' + ', '.join(dlt) + ')' if dlt else ''} FROM bronze_raw.{raw}"


def rebuild_bronze(con, tables: tuple[str, ...] = tuple(RAW)) -> None:
    """Bronze = tabelas (não views): o código compartilhado e os testes das Fases 1–3 alteram a Bronze no lugar."""
    for t in tables:
        parts = [_raw_select(con, r) for r in RAW[t] if _columns(con, "bronze_raw", r)]
        if parts:
            con.execute(f"CREATE OR REPLACE TABLE bronze.{t} AS " + " UNION ALL BY NAME ".join(parts))


def bridge_load(con, path: str) -> None:
    """Cópia de referência: o que as fontes entregaram (armazém das fontes) → bronze_raw → Bronze, numa transação."""
    con.execute(f"ATTACH '{path}' AS fontes (READ_ONLY)")
    try:
        con.execute("BEGIN")
        con.execute("CREATE OR REPLACE TABLE bronze_raw.ad_spend AS FROM fontes.bronze.ad_spend")
        con.execute("CREATE OR REPLACE TABLE bronze_raw.campaigns AS FROM fontes.bronze.campaigns")
        con.execute("CREATE OR REPLACE TABLE bronze_raw.conversions__ga4 AS "
                    "FROM fontes.bronze.conversions WHERE source = 'ga4'")
        con.execute("CREATE OR REPLACE TABLE bronze_raw.conversions__meta_capi AS "
                    "FROM fontes.bronze.conversions WHERE source = 'meta_capi'")
        # O backlog da Meta acompanha a ponte: o `generate.backfill_meta` compartilhado roda sobre o lake nos testes.
        con.execute("CREATE OR REPLACE TABLE meta.upstream_backlog AS FROM fontes.meta.upstream_backlog")
        rebuild_bronze(con)
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    finally:
        con.execute("DETACH fontes")


def reset_stack(con, now: datetime) -> None:
    """Lake e estado operacional zerados; o estado vivo das campanhas semeado pelo código compartilhado."""
    from agentready_stack import warehouse
    warehouse.reset(con)
    generate.create_ops_tables(con)
    generate.seed_live_state(con, now)


# ----------------------------------------------------------------------------------------------- US1: admin das fontes

class UpstreamError(RuntimeError):
    """A fonte recusou (409, mensagem pt-BR dela) ou está fora do ar."""


def admin_call(method: str, path: str, body: dict | None = None, timeout: float = 120) -> dict:
    """Chama a administração das fontes simuladas (porta interna 8001, nunca publicada)."""
    import urllib.error
    import urllib.request
    base = os.environ.get("UPSTREAM_ADMIN_URL")
    if not base:
        raise IngestionConfigError("UPSTREAM_ADMIN_URL não definido (administração das fontes simuladas)")
    req = urllib.request.Request(base.rstrip("/") + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            msg = json.loads(e.read()).get("erro") or str(e)
        except Exception:  # noqa: BLE001
            msg = str(e)
        raise UpstreamError(f"a fonte recusou: {msg}") from e
    except OSError as e:
        raise UpstreamError(f"fontes simuladas fora do ar ({base}): {e}") from e


def mirror_incident(con, row: dict) -> None:
    """O registro do incidente (TTD/TTR) fica no ops.incidents da stack, espelhado da fonte."""
    has_bronze = con.execute("SELECT count(*) FROM information_schema.tables WHERE table_catalog=current_database() "
                             "AND table_schema='bronze' AND table_name='conversions'").fetchone()[0]
    if has_bronze:
        incidents.open_incident(con)          # o código compartilhado cria ops.incidents (precisa da Bronze)
    else:
        # Primeira execução com reset + incidente: a Bronze ainda não chegou. Mesma forma do incidents._ensure.
        con.execute("""CREATE TABLE IF NOT EXISTS ops.incidents (incident_id VARCHAR, kind VARCHAR,
            injected_at TIMESTAMP, detected_at TIMESTAMP, resolved_at TIMESTAMP, batch_id VARCHAR)""")
    con.execute("INSERT INTO ops.incidents VALUES (?,?,?,?,?,?)",
                [row["incident_id"], row["kind"], row["injected_at"], row.get("detected_at"), row.get("resolved_at"),
                 row.get("batch_id")])


# ----------------------------------------------------------------------------------------------- US1: dlt

CONFIG_PATH = Path(os.environ.get("STACK_INGESTION_CONFIG",
                                  str(Path(__file__).resolve().parents[3] / "ingestion" / "fontes.yaml")))
STATUS = ("carregado", "sem_dados_novos", "falhou")


class IngestionConfigError(RuntimeError):
    """Erro de configuração da ingestão (YAML, URL, lake): sai com código 1."""


def config() -> dict:
    import yaml
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            return yaml.safe_load(f)
    except OSError as e:
        raise IngestionConfigError(f"configuração da ingestão ilegível: {CONFIG_PATH} ({e})") from e


def upstream_url() -> str:
    u = os.environ.get("UPSTREAM_URL")
    if not u:
        raise IngestionConfigError("UPSTREAM_URL não definido (endereço das fontes simuladas)")
    return u.rstrip("/")


def ensure_loads(con) -> None:
    con.execute("""CREATE TABLE IF NOT EXISTS ops.ingestion_loads (load_id VARCHAR, dag_run_id VARCHAR, fonte VARCHAR,
        status VARCHAR, motivo VARCHAR, manifesto JSON, lotes_novos VARCHAR[], lotes_retirados VARCHAR[],
        lotes_inalterados VARCHAR[], linhas BIGINT, tentativas_http INTEGER, snapshot_id BIGINT,
        iniciado_em TIMESTAMP, terminado_em TIMESTAMP)""")


def _last_loaded_manifest(con, fonte: str) -> list[dict] | None:
    r = con.execute("SELECT manifesto FROM ops.ingestion_loads WHERE fonte = ? AND status = 'carregado' "
                    "ORDER BY terminado_em DESC LIMIT 1", [fonte]).fetchall()
    return json.loads(r[0][0]) if r else None


def diff_manifest(prev: list[dict] | None, cur: list[dict]) -> tuple[list[str], list[str], list[str]]:
    """(novos, retirados, inalterados) por batch_id; um lote com checksum diferente conta como novo."""
    p = {b["batch_id"]: b["checksum"] for b in (prev or [])}
    c = {b["batch_id"]: b["checksum"] for b in cur}
    novos = sorted(b for b in c if p.get(b) != c[b])
    retirados = sorted(b for b in p if b not in c)
    inalterados = sorted(b for b in c if p.get(b) == c[b])
    return novos, retirados, inalterados


class _Counter:
    """Conta respostas de erro da fonte (cada uma vira uma nova tentativa do cliente do dlt)."""
    def __init__(self) -> None:
        self.retries = 0


def _client(http: dict, counter: _Counter):
    """Sessão do cliente do dlt (novas tentativas com backoff, respeitando Retry-After). A contagem fica no adaptador
    HTTP: o dlt prepara as requisições e embrulha `session.send` com as novas tentativas, então só o adaptador vê
    cada tentativa."""
    from dlt.sources.helpers.requests import Client
    from requests.adapters import HTTPAdapter

    class _CountingAdapter(HTTPAdapter):
        def send(self, request, *a, **k):
            resp = super().send(request, *a, **k)
            if resp.status_code >= 500 or resp.status_code == 429:
                counter.retries += 1
            return resp

    c = Client(request_timeout=http["timeout_s"], request_max_attempts=http["max_attempts"],
               request_backoff_factor=http["backoff_factor"], request_max_retry_delay=http["max_retry_delay_s"],
               respect_retry_after_header=True)
    session = c.session
    session.mount("http://", _CountingAdapter())
    session.mount("https://", _CountingAdapter())
    return session


def _fetch_manifest(session, base: str, headers: dict) -> list[dict]:
    r = session.get(f"{base}/lotes", headers=headers)
    r.raise_for_status()
    return r.json()["lotes"]


def _dlt_load(fonte: str, f: dict, http: dict, base: str, headers: dict, session, workdir: str) -> list[str]:
    """dlt extrai, normaliza e grava Parquet num bucket temporário; devolve os arquivos da tabela da fonte."""
    import dlt
    from dlt.sources.rest_api import rest_api_source
    cols = {c: {"data_type": "text", "nullable": True} for c in f["colunas"]}
    cols["ingested_at"] = {"data_type": "timestamp", "timezone": False, "nullable": True}
    src = rest_api_source({
        "client": {"base_url": base + "/", "headers": headers, "session": session},
        "resource_defaults": {"write_disposition": "replace"},
        "resources": [{
            "name": f["dlt_tabela"], "columns": cols,
            "endpoint": {"path": f["recurso"], "params": {"page_size": http["page_size"]}, "data_selector": "data",
                         "paginator": {"type": "page_number", "base_page": 1, "page_param": "page",
                                       "total_path": None, "stop_after_empty_page": True}}}]})
    bucket = os.path.join(workdir, "bucket")
    p = dlt.pipeline(f"aurora_{fonte}", destination=dlt.destinations.filesystem(bucket_url=f"file://{bucket}"),
                     dataset_name="bronze_raw", pipelines_dir=os.path.join(workdir, "pipelines"))
    info = p.run(src, loader_file_format="parquet")
    if info.has_failed_jobs:
        raise RuntimeError(f"{fonte}: o dlt registrou jobs com falha na carga")
    return sorted(glob.glob(os.path.join(bucket, "bronze_raw", f["dlt_tabela"], "*.parquet")))


def _commit(con, f: dict, files: list[str]) -> int:
    """Uma transação: bronze_raw.<raw> trocada pelos arquivos desta carga + Bronze reconstruída (um snapshot)."""
    lst = "[" + ", ".join("'" + x.replace("'", "''") + "'" for x in files) + "]"
    present = [r[0] for r in con.execute(f"DESCRIBE SELECT * FROM read_parquet({lst}, union_by_name = true)").fetchall()]
    ordered = [c for c in f["colunas"] if c in present]
    extra = [c for c in present if c not in ordered and c not in DLT_COLUMNS]
    tail = [c for c in DLT_COLUMNS if c in present]
    sel = ", ".join(f'"{c}"' for c in ordered + extra + tail)
    con.execute("BEGIN")
    try:
        con.execute(f"CREATE OR REPLACE TABLE bronze_raw.{f['raw']} AS SELECT {sel} "
                    f"FROM read_parquet({lst}, union_by_name = true)")
        n = con.execute(f"SELECT count(*) FROM bronze_raw.{f['raw']}").fetchone()[0]
        rebuild_bronze(con, (f["bronze"],))
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    return n


def run_source(fonte: str, dag_run_id: str | None = None) -> dict:
    """Uma carga de uma fonte (contracts/ingestion.md → "Algorithm"). Código 0 em todo status, inclusive `falhou`:
    uma fonte fora do ar não derruba as outras nem a execução; o frescor dela vence sozinho (Princípio III)."""
    from agentready_stack import lake, telemetry, warehouse
    cfg = config()
    if fonte not in cfg["fontes"]:
        raise IngestionConfigError(f"fonte desconhecida: {fonte}. Use {tuple(cfg['fontes'])}")
    os.environ.setdefault("RUNTIME__DLTHUB_TELEMETRY", "false" if not cfg["runtime"]["dlthub_telemetry"] else "true")
    f, http = cfg["fontes"][fonte], cfg["http"]
    base = f"{upstream_url()}/{f['rota']}/v1"
    headers = {"X-Execucao": dag_run_id or "manual"}
    counter = _Counter()
    session = _client(http, counter)
    started = datetime.now()
    status, motivo, manifest, linhas, snap = "falhou", None, [], None, None
    novos, retirados, inalterados = [], [], []
    con = warehouse.connect()
    try:
        ensure_loads(con)
        try:
            manifest = _fetch_manifest(session, base, headers)
            prev = _last_loaded_manifest(con, fonte)
            novos, retirados, inalterados = diff_manifest(prev, manifest)
            if prev is not None and not novos and not retirados:
                status = "sem_dados_novos"
            else:
                with tempfile.TemporaryDirectory(prefix=f"ingestao-{fonte}-") as work:
                    files = _dlt_load(fonte, f, http, base, headers, session, work)
                    if not files:
                        raise RuntimeError(f"{fonte}: a fonte não devolveu nenhuma linha")
                    linhas = _commit(con, f, files)
                snap = warehouse.lake_snapshot_id(con)
                lake.checkpoint(con, f"ingestao.{fonte}", dag_run_id, lotes=novos)
                status = "carregado"
        except Exception as e:  # noqa: BLE001 — qualquer falha de carga vira `falhou` com motivo
            status, linhas, snap = "falhou", None, None
            motivo = _motivo(fonte, e, http)
        con.execute("INSERT INTO ops.ingestion_loads VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    ["LD-" + uuid.uuid4().hex[:8], dag_run_id, fonte, status, motivo, json.dumps(manifest),
                     novos, retirados, inalterados, linhas, counter.retries, snap, started, datetime.now()])
    finally:
        con.close()
    with telemetry.ingestao_carga(dag_run_id, fonte, status, motivo, novos, retirados, linhas, counter.retries, snap):
        pass
    return {"fonte": fonte, "status": status, "motivo": motivo, "lotes_novos": novos, "lotes_retirados": retirados,
            "lotes_inalterados": inalterados, "linhas": linhas, "tentativas_http": counter.retries,
            "snapshot_id": snap}


def _motivo(fonte: str, e: Exception, http: dict) -> str:
    text = str(e)
    for code in ("503", "500", "502", "504", "429"):
        if code in text:
            return f"{fonte}: fonte indisponível após {http['max_attempts']} tentativas ({code})"
    if isinstance(e, (ConnectionError, OSError)) or "Connection" in type(e).__name__:
        return f"{fonte}: fonte inacessível ({type(e).__name__})"
    return f"{fonte}: carga falhou ({type(e).__name__}: {text[:200]})"


def summary_line(r: dict) -> str:
    """Linha pt-BR do log da tarefa, ex.: `ga4: 2 lotes novos, 1 retirado, 4.812 linhas (1 nova tentativa após 503)`."""
    def n(x: int) -> str:
        return f"{x:,}".replace(",", ".")
    if r["status"] == "falhou":
        return f"{r['fonte']}: FALHOU — {r['motivo']}"
    if r["status"] == "sem_dados_novos":
        return f"{r['fonte']}: sem dados novos (manifesto igual ao da última carga)"
    parts = [f"{len(r['lotes_novos'])} lote(s) novo(s)"]
    if r["lotes_retirados"]:
        parts.append(f"{len(r['lotes_retirados'])} retirado(s)")
    parts.append(f"{n(r['linhas'])} linhas")
    retry = f" ({r['tentativas_http']} nova(s) tentativa(s) após erro da fonte)" if r["tentativas_http"] else ""
    return f"{r['fonte']}: " + ", ".join(parts) + retry
