"""Fase 4 — ingestão pelo dlt a partir das fontes simuladas (contracts/ingestion.md, data-model §4).

As fontes rodam numa thread deste processo (assim um teste pode trocar `deve_falhar`); cada carga roda como a
tarefa do DAG: `agentready-stack task ingest-fonte <fonte>` no venv da ingestão (dlt + DuckDB 2.0.1).
"""
import json
import os
import socket
import subprocess
import threading
import time
import urllib.request

import pytest

from agentready_stack import ingestion, upstream_app, warehouse

INGEST_PY = os.environ.get("STACK_INGEST_PYTHON", "/opt/venvs/ingest/bin/python")
FONTES = ("ads", "ga4", "meta_capi", "catalogo")
TABLES = ("campaigns", "ad_spend", "conversions")


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture
def upstream(built, monkeypatch):
    """Fontes simuladas sobre o armazém do cenário (o mesmo que a ponte carregou no lake)."""
    import uvicorn
    monkeypatch.setitem(upstream_app.STORE, "path", ingestion.store_path())
    monkeypatch.setattr(upstream_app, "_planos", {})
    monkeypatch.setattr(upstream_app, "_tentativas", {})
    pub, adm = _free_port(), _free_port()
    servers = [uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=p, log_level="warning"))
               for app, p in ((upstream_app.public_app, pub), (upstream_app.admin_app, adm))]
    threads = [threading.Thread(target=s.run, daemon=True) for s in servers]
    for t in threads:
        t.start()
    for _ in range(100):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{pub}/saude", timeout=1).read()
            break
        except OSError:
            time.sleep(0.1)
    yield {"url": f"http://127.0.0.1:{pub}", "admin": f"http://127.0.0.1:{adm}"}
    for s in servers:
        s.should_exit = True
    for t in threads:
        t.join(timeout=5)


def plan(up, run_id, falhas="padrao", fora="nenhuma"):
    req = urllib.request.Request(f"{up['admin']}/admin/falhas", method="PUT", headers={"Content-Type": "application/json"},
                                 data=json.dumps({"execucao": run_id, "falhas_upstream": falhas,
                                                  "fonte_fora_do_ar": fora}).encode())
    urllib.request.urlopen(req, timeout=5).read()


def ingest(up, fonte, run_id="run-1"):
    r = subprocess.run([INGEST_PY, "-m", "agentready_stack.cli", "task", "ingest-fonte", fonte, "--dag-run-id", run_id],
                       capture_output=True, text=True, timeout=300, env=os.environ | {"UPSTREAM_URL": up["url"]})
    assert r.returncode == 0, r.stderr[-2000:]
    return json.loads(r.stdout.strip().splitlines()[-1])


def _shape(con, catalog, table):
    cols = [r[0] for r in con.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_catalog=? AND table_schema='bronze' "
        "AND table_name=? ORDER BY ordinal_position", [catalog, table]).fetchall()]
    by_batch = {b: (n, h) for b, n, h in con.execute(
        f"SELECT batch_id, count(*), bit_xor(hash(t)) FROM {catalog}.bronze.{table} t GROUP BY batch_id").fetchall()}
    return cols, by_batch


def _bronze_equals_store():
    c = warehouse.connect()
    try:
        c.execute(f"ATTACH '{ingestion.store_path()}' AS fontes (READ_ONLY)")
        for t in TABLES:
            assert _shape(c, "warehouse", t) == _shape(c, "fontes", t), t
        c.execute("DETACH fontes")
    finally:
        c.close()


def _loads():
    c = warehouse.connect()
    try:
        return [dict(zip(("fonte", "status", "motivo", "linhas", "snapshot_id", "novos", "tentativas"), r))
                for r in c.execute("SELECT fonte, status, motivo, linhas, snapshot_id, lotes_novos, tentativas_http "
                                   "FROM ops.ingestion_loads ORDER BY terminado_em").fetchall()]
    finally:
        c.close()


def _drop_raw():
    """Começa a ingestão do zero: a ponte do cenário encheu o lake; aqui só o dlt escreve."""
    c = warehouse.connect()
    try:
        for t in ("ad_spend", "campaigns", "conversions__ga4", "conversions__meta_capi"):
            c.execute(f"DROP TABLE IF EXISTS bronze_raw.{t}")
        for t in TABLES:
            c.execute(f"DROP TABLE IF EXISTS bronze.{t}")
    finally:
        c.close()


def test_ingest_venv_has_every_import_it_needs():
    r = subprocess.run([INGEST_PY, "-c", "import agentready_stack.ingestion, agentready_stack.lake, "
                        "agentready_stack.telemetry, dlt, duckdb; print(duckdb.__version__)"], capture_output=True, text=True)
    assert r.returncode == 0 and r.stdout.strip() == "2.0.1", r.stderr[-1000:]


def test_four_sources_rebuild_exactly_the_generator_bronze(upstream):
    _drop_raw()
    plan(upstream, "run-1")
    out = {f: ingest(upstream, f) for f in FONTES}
    assert all(o["status"] == "carregado" for o in out.values()), out
    assert out["ga4"]["tentativas_http"] >= 1, "o plano padrão derruba a página 2 do ga4 uma vez"
    _bronze_equals_store()
    c = warehouse.connect()
    try:
        assert c.execute("SELECT typeof(ingested_at) FROM bronze.conversions LIMIT 1").fetchone()[0] == "TIMESTAMP"
        batches = {r[0] for r in c.execute("SELECT DISTINCT batch_id FROM bronze.conversions").fetchall()}
        assert any(b.endswith("-retry") for b in batches)
        assert c.execute("SELECT count(*) FROM bronze.conversions WHERE campaign_id='C99'").fetchone()[0] > 0
        assert c.execute("SELECT count(*) FROM bronze.conversions WHERE campaign_id IS NULL").fetchone()[0] > 0
        assert c.execute("SELECT count(*) FROM bronze.conversions WHERE order_value_brl LIKE '%,%'").fetchone()[0] > 0
        assert set(c.execute("SELECT column_name FROM information_schema.columns WHERE table_catalog='warehouse' "
                             "AND table_schema='bronze_raw' AND table_name='conversions__ga4'").fetchall()) >= {
            ("_dlt_load_id",), ("_dlt_id",)}
    finally:
        c.close()
    # dados conferem com os registros
    for row in _loads():
        assert row["status"] == "carregado" and row["linhas"] > 0 and row["snapshot_id"] is not None and row["motivo"] is None


def test_unchanged_sources_write_nothing(upstream):
    plan(upstream, "run-1")
    for f in FONTES:
        ingest(upstream, f, "run-1")
    c = warehouse.connect()
    snap = warehouse.lake_snapshot_id(c)
    c.close()
    plan(upstream, "run-2")
    second = [ingest(upstream, f, "run-2") for f in FONTES]
    assert all(o["status"] == "sem_dados_novos" for o in second), second
    assert all(o["linhas"] is None and o["snapshot_id"] is None for o in second), "desconhecido é NULL, nunca 0"
    c = warehouse.connect()
    assert warehouse.lake_snapshot_id(c) == snap, "sem mudança na fonte, nenhum snapshot novo"
    c.close()


def test_retries_on_every_page_never_duplicate(upstream):
    _drop_raw()
    plan(upstream, "todas", falhas="todas")
    out = [ingest(upstream, f, "todas") for f in FONTES]
    assert all(o["status"] == "carregado" and o["tentativas_http"] >= 1 for o in out), out
    _bronze_equals_store()


def test_source_down_fails_alone_and_keeps_bronze(upstream):
    plan(upstream, "ok")
    for f in FONTES:
        ingest(upstream, f, "ok")
    c = warehouse.connect()
    before = c.execute("SELECT count(*), bit_xor(hash(t)) FROM bronze_raw.conversions__ga4 t").fetchone()
    c.close()
    # a fonte muda (backfill da Meta) e o ga4 cai a execução inteira
    src = ingestion.store_connect(ingestion.store_path())
    from agentready import generate
    generate.backfill_meta(src)
    src.close()
    plan(upstream, "fora", fora="ga4")
    out = {f: ingest(upstream, f, "fora") for f in FONTES}
    assert out["ga4"]["status"] == "falhou"
    assert out["ga4"]["motivo"] == "ga4: fonte indisponível após 4 tentativas (503)"
    assert out["meta_capi"]["status"] == "carregado" and len(out["meta_capi"]["lotes_novos"]) == 3
    c = warehouse.connect()
    assert c.execute("SELECT count(*), bit_xor(hash(t)) FROM bronze_raw.conversions__ga4 t").fetchone() == before
    c.close()
    failed = [r for r in _loads() if r["status"] == "falhou"]
    assert failed and failed[-1]["linhas"] is None and failed[-1]["snapshot_id"] is None and failed[-1]["motivo"]


def test_a_page_that_never_comes_back_commits_nothing(upstream, monkeypatch):
    plan(upstream, "ok")
    ingest(upstream, "ga4", "ok")
    c = warehouse.connect()
    before = c.execute("SELECT count(*) FROM bronze_raw.conversions__ga4").fetchone()[0]
    c.close()
    src = ingestion.store_connect(ingestion.store_path())
    src.execute("UPDATE bronze.conversions SET order_value_brl = '1.00' WHERE source = 'ga4' AND conversion_id = "
                "(SELECT min(conversion_id) FROM bronze.conversions WHERE source = 'ga4')")      # a fonte mudou
    src.close()
    monkeypatch.setattr(upstream_app, "deve_falhar", lambda plano, ex, fonte, pagina, t: fonte == "ga4" and pagina == 3)
    out = ingest(upstream, "ga4", "parcial")
    assert out["status"] == "falhou" and out["motivo"].startswith("ga4:")
    c = warehouse.connect()
    assert c.execute("SELECT count(*) FROM bronze_raw.conversions__ga4").fetchone()[0] == before
    c.close()


def test_ingest_path_never_calls_the_generator():
    src = open(ingestion.__file__, encoding="utf-8").read()
    run_source = src[src.index("def run_source"):src.index("def _motivo")]
    assert "generate." not in run_source and "store_generate" not in run_source
