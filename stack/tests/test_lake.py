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
