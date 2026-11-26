"""Fase 4 — a Bronze do lake é exatamente a Bronze que o gerador compartilhado escreve (carga de referência).

A trilha padrão escreve a Bronze direto; a stack carrega a partir das fontes. Mesmas colunas, mesmas linhas e o mesmo
checksum por lote — é isso que deixa a paridade (Gold, saúde, decisões) em zero.
"""
import duckdb

from agentready_stack import ingestion, warehouse

TABLES = ("campaigns", "ad_spend", "conversions")


def _shape(con, catalog: str, table: str):
    cols = [r[0] for r in con.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_catalog=? AND table_schema='bronze' "
        "AND table_name=? ORDER BY ordinal_position", [catalog, table]).fetchall()]
    by_batch = {b: (n, h) for b, n, h in con.execute(
        f"SELECT batch_id, count(*), bit_xor(hash(t)) FROM {catalog}.bronze.{table} t GROUP BY batch_id").fetchall()}
    return cols, by_batch


def test_lake_bronze_equals_the_generator_bronze(built):
    c = warehouse.connect()
    try:
        c.execute(f"ATTACH '{ingestion.store_path()}' AS fontes (READ_ONLY)")
        for t in TABLES:
            lake_cols, lake_batches = _shape(c, "warehouse", t)
            src_cols, src_batches = _shape(c, "fontes", t)
            assert lake_cols == src_cols, (t, lake_cols, src_cols)
            assert lake_batches == src_batches, t
        # problemas plantados chegaram como o gerador os escreveu
        batches = {r[0] for r in c.execute("SELECT DISTINCT batch_id FROM bronze.conversions").fetchall()}
        assert any(b.endswith("-retry") for b in batches), "o lote duplicado do ga4 tem de estar na Bronze"
        assert c.execute("SELECT count(*) FROM bronze.conversions WHERE campaign_id = 'C99'").fetchone()[0] > 0
        assert c.execute("SELECT count(*) FROM bronze.conversions WHERE order_value_brl LIKE '%,%'").fetchone()[0] > 0
        c.execute("DETACH fontes")
    finally:
        c.close()


def test_live_state_is_seeded_in_ops_with_its_primary_key(built):
    c = warehouse.connect()
    try:
        assert c.execute("SELECT count(*) FROM ops.campaigns WHERE status = 'active'").fetchone()[0] == 6
        try:
            c.execute("INSERT INTO ops.campaigns SELECT * FROM ops.campaigns LIMIT 1")
            raise AssertionError("ops.campaigns perdeu a chave primária")
        except duckdb.ConstraintException:
            pass
    finally:
        c.close()
