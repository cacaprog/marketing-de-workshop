"""Fase 4 — o lake (DuckLake) e o estado operacional (ops.duckdb) numa conexão só (pesquisa R2, contracts/lake-snapshots.md)."""
import os

import pytest

from agentready_stack import ingestion, lake, warehouse


def _schemas(c):
    return {r[0] for r in c.execute("SELECT schema_name FROM information_schema.schemata WHERE catalog_name='warehouse'"
                                    ).fetchall()}


# ---------------------------------------------------------------- conexão

def test_connect_makes_the_lake_current_and_ops_a_catalog():
    c = warehouse.connect()
    try:
        assert c.execute("SELECT current_database()").fetchone()[0] == "warehouse"
        c.execute("CREATE TABLE IF NOT EXISTS ops.autonomy_override (level VARCHAR)")   # como o autonomy.py compartilhado
        c.execute("CREATE OR REPLACE TABLE gold.teste_conexao AS SELECT 1 AS x")
        where = dict(c.execute("SELECT table_name, table_catalog || '.' || table_schema FROM information_schema.tables "
                               "WHERE table_name IN ('autonomy_override', 'teste_conexao')").fetchall())
        assert where == {"autonomy_override": "ops.main", "teste_conexao": "warehouse.gold"}
        assert "ops" not in _schemas(c), "o lake nunca pode ter um schema ops (os snapshots não podem tocar o estado vivo)"
        assert set(warehouse.DATA_SCHEMAS) <= _schemas(c)
        c.execute("DROP TABLE gold.teste_conexao")
    finally:
        c.close()


def test_extensions_come_only_from_the_image():
    c = warehouse.connect()
    try:
        assert c.execute("SELECT current_setting('autoinstall_known_extensions')").fetchone()[0] is False
        ext = os.environ.get("STACK_DUCKDB_EXTENSIONS")
        if ext:
            assert c.execute("SELECT current_setting('extension_directory')").fetchone()[0] == ext
    finally:
        c.close()


def test_connect_refuses_a_file_that_is_not_ops(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENTREADY_DB", str(tmp_path / "warehouse.duckdb"))
    with pytest.raises(warehouse.WarehouseError, match="ops.duckdb"):
        warehouse.connect()


def test_lake_never_gets_an_ops_schema_after_a_full_scenario(built):
    c = warehouse.connect()
    try:
        assert "ops" not in _schemas(c)
        assert c.execute("SELECT count(*) FROM ops.campaigns").fetchone()[0] == 6
        assert c.execute("SELECT count(*) FROM gold.campaign_daily").fetchone()[0] > 0
    finally:
        c.close()


# ---------------------------------------------------------------- marcos (checkpoints)

def test_checkpoint_records_the_snapshot_and_rejects_unknown_stages(built):
    c = warehouse.connect()
    try:
        snap = warehouse.lake_snapshot_id(c)
        ck = lake.checkpoint(c, "ingestao.ga4", "run-1", lotes=["ga4-2026-11-24"])
        row = c.execute("SELECT etapa, snapshot_id, dag_run_id, lotes, incident_id FROM ops.lake_checkpoints "
                        "WHERE checkpoint_id = ?", [ck]).fetchone()
        assert ck.startswith("CK-") and row == ("ingestao.ga4", snap, "run-1", ["ga4-2026-11-24"], None)
        with pytest.raises(ValueError, match="etapa inválida"):
            lake.checkpoint(c, "gold")
        assert ingestion.RAW["conversions"] == ("conversions__ga4", "conversions__meta_capi")
    finally:
        c.close()


# ---------------------------------------------------------------- snapshots, viagem no tempo, restauração (US2)

def _ops_fingerprint(c):
    return {t: c.execute(f"SELECT count(*), bit_xor(hash(x)) FROM ops.main.{t} x").fetchone()
            for t in warehouse.ops_tables(c) if t not in ("lake_checkpoints", "lake_restores")}


def test_snapshots_list_named_checkpoints(built):
    c = warehouse.connect()
    try:
        lake.checkpoint(c, "agente", "run-x")
        marks = lake.snapshots(c)
        assert marks[0]["etapa"] == "agente" and marks[0]["dag_run_id"] == "run-x"
        assert marks[-1]["commits_desde_o_anterior"] >= 1
        assert all(m["checkpoint_id"].startswith("CK-") for m in marks)
    finally:
        c.close()


def test_consultar_em_reads_any_layer_at_a_snapshot_and_refuses_ops(built):
    c = warehouse.connect()
    try:
        n = warehouse.lake_snapshot_id(c)
        before = c.execute("SELECT count(*) FROM gold.campaign_daily").fetchone()[0]
        c.execute("DELETE FROM gold.campaign_daily WHERE campaign_id = 'C01'")
        cols, rows = lake.consultar_em(c, "gold.campaign_daily", n, limite=100000)
        assert "campaign_id" in cols and len(rows) == before, "o snapshot antigo ainda tem a C01"
        ts = c.execute(f"SELECT snapshot_time FROM ducklake_snapshots('warehouse') WHERE snapshot_id = {n}").fetchone()[0]
        _c2, rows_t = lake.consultar_em(c, "gold.campaign_daily", ts.strftime("%Y-%m-%d %H:%M:%S.%f"), limite=100000)
        assert len(rows_t) == before
        with pytest.raises(lake.RestoreRefused, match="estado operacional"):
            lake.consultar_em(c, "ops.campaigns", n)
        with pytest.raises(lake.NotFound):
            lake.consultar_em(c, "gold.nao_existe", n)
    finally:
        c.close()


def test_restore_is_one_new_snapshot_keeps_history_is_undoable_and_never_touches_ops(built):
    c = warehouse.connect()
    try:
        ck = lake.checkpoint(c, "gold_observabilidade")
        n = warehouse.lake_snapshot_id(c)
        gold_n = c.execute("SELECT count(*), bit_xor(hash(g)) FROM gold.campaign_daily g").fetchone()
        ops_before = _ops_fingerprint(c)
        # o lote ruim chega e uma tabela nova aparece depois do snapshot n
        c.execute("UPDATE bronze.conversions SET order_value_brl = '99999' WHERE source = 'ga4'")
        c.execute("DELETE FROM gold.campaign_daily WHERE campaign_id = 'C01'")
        c.execute("CREATE TABLE meta.depois_do_snapshot AS SELECT 1 AS x")
        bad = warehouse.lake_snapshot_id(c)
        r = lake.restore(c, ck, "teste")
        assert r["para_snapshot"] == n and r["de_snapshot"] == bad and r["novo_snapshot"] == bad + 1, r
        assert "meta.depois_do_snapshot" in r["removidas"]
        assert c.execute("SELECT count(*), bit_xor(hash(g)) FROM gold.campaign_daily g").fetchone() == gold_n
        assert c.execute("SELECT count(*) FROM bronze.conversions WHERE order_value_brl = '99999'").fetchone()[0] == 0
        assert _ops_fingerprint(c) == ops_before, "restauração nunca toca o ops.duckdb"
        assert {bad, r["novo_snapshot"]} <= {s for s, in c.execute(
            "SELECT snapshot_id FROM ducklake_snapshots('warehouse')").fetchall()}, "a história fica"
        row = c.execute("SELECT restore_id, de_snapshot, para_snapshot, novo_snapshot, por, motivo, incident_id "
                        "FROM ops.lake_restores").fetchone()
        assert row[0].startswith("RS-") and row[1:] == (bad, n, r["novo_snapshot"], "instrutor", "teste", None)
        assert c.execute("SELECT etapa FROM ops.lake_checkpoints ORDER BY criado_em DESC LIMIT 1").fetchone()[0] == "restauracao"
        # desfazer: voltar ao snapshot de antes da restauração traz o estado ruim de volta
        lake.restore(c, bad, "desfazer")
        assert c.execute("SELECT count(*) FROM bronze.conversions WHERE order_value_brl = '99999'").fetchone()[0] > 0
    finally:
        c.close()


def test_restore_guards(built, monkeypatch):
    c = warehouse.connect()
    try:
        n = warehouse.lake_snapshot_id(c)
        monkeypatch.setattr(lake, "airflow_active_runs", lambda: ["manual__rodando"])
        with pytest.raises(lake.RestoreRefused, match="em andamento"):
            lake.restore(c, n - 1, "x")
        monkeypatch.setattr(lake, "airflow_active_runs", lambda: [])
        with pytest.raises(lake.RestoreRefused, match="não existe"):
            lake.restore(c, 10_000_000, "x")
        with pytest.raises(lake.RestoreRefused, match="já está"):
            lake.restore(c, n, "x")
        lake.checkpoint(c, "reset")
        with pytest.raises(lake.RestoreRefused, match="antes do último reset"):
            lake.restore(c, 1, "x")
    finally:
        c.close()


def test_gold_as_of_a_decision_reads_the_agent_checkpoint(built):
    from agentready import tracing
    from agentready_stack import tasks
    out = tasks.run_agent("rules", False, "run-gold")
    tracing.flush()
    c = warehouse.connect()
    try:
        snap = c.execute("SELECT snapshot_id FROM ops.lake_checkpoints WHERE etapa='agente' AND dag_run_id='run-gold'"
                         ).fetchone()[0]
        g = lake.gold_as_of(c, out["trace_id"])
        assert g["snapshot_id"] == snap and g["dag_run_id"] == "run-gold" and g["linhas"]
        expected = c.execute(f"SELECT count(*) FROM gold.campaign_daily AT (VERSION => {snap}) "
                             "WHERE day >= (SELECT max(day) FROM gold.campaign_daily) - INTERVAL 13 DAY").fetchone()[0]
        assert len(g["linhas"]) == expected
        chg = c.execute("SELECT change_id, campaign_id FROM ops.change_log WHERE trace_id = ? LIMIT 1",
                        [out["trace_id"]]).fetchall()
        if chg:
            gc = lake.gold_as_of(c, chg[0][0])
            assert gc["campaign_id"] == chg[0][1] and {r[gc["colunas"].index("campaign_id")] for r in gc["linhas"]} == {chg[0][1]}
        with pytest.raises(lake.NotFound):
            lake.gold_as_of(c, "CHG-00000000")
    finally:
        c.close()
