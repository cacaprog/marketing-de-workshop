"""Fase 4 — resolver um incidente: a fonte faz o rollback e as camadas voltam ao último estado limpo (restauração)."""
from agentready_stack import incidents_cli, lake, tasks, warehouse


def _gold_and_health(c):
    return (c.execute("SELECT count(*), bit_xor(hash(g)) FROM gold.campaign_daily g").fetchone(),
            c.execute("SELECT count(*), bit_xor(hash(h)) FROM gold.source_health h").fetchone())


def test_centavos_resolve_restores_the_clean_agent_checkpoint(built, dbt):
    c = warehouse.connect()
    try:
        lake.checkpoint(c, "agente", "limpa")
        clean = _gold_and_health(c)
        ops_before = c.execute("SELECT count(*), bit_xor(hash(x)) FROM ops.campaigns x").fetchone()
        chg_before = c.execute("SELECT count(*) FROM ops.change_log").fetchone()[0]
    finally:
        c.close()
    tasks.ingest({"incident": "centavos"})
    dbt()
    c = warehouse.connect()
    try:
        assert _gold_and_health(c) != clean, "o centavos mudou a Gold"
    finally:
        c.close()
    m = incidents_cli.resolve()
    assert m["resolved_at"] is not None and m["TTR_min"] is not None
    c = warehouse.connect()
    try:
        assert _gold_and_health(c) == clean, "Gold e saúde das fontes iguais às da execução limpa"
        assert c.execute("SELECT count(*), bit_xor(hash(x)) FROM ops.campaigns x").fetchone() == ops_before
        assert c.execute("SELECT count(*) FROM ops.change_log").fetchone()[0] == chg_before
        r = c.execute("SELECT motivo, incident_id FROM ops.lake_restores").fetchone()
        assert r[1] == m["incident_id"] and "resolvido" in r[0]
    finally:
        c.close()


def test_without_an_agent_checkpoint_it_falls_back_and_warns(built, capsys):
    tasks.ingest({"incident": "lote_duplicado"})
    capsys.readouterr()
    incidents_cli.resolve()
    assert "não há marco `agente`" in capsys.readouterr().out


def test_only_a_reset_before_the_incident_closes_it_without_emptying_the_lake(built, capsys):
    """Achado do test-live: sem marco completo antes da injeção (só `reset`), resolver NÃO restaura (restaurar para
    um marco incompleto esvaziaria o lake); a fonte volta ao normal e o incidente fecha com aviso."""
    c = warehouse.connect()
    try:
        c.execute("DELETE FROM ops.lake_checkpoints")
        lake.checkpoint(c, "reset")
    finally:
        c.close()
    tasks.ingest({"incident": "centavos"})
    capsys.readouterr()
    m = incidents_cli.resolve()
    assert m["resolved_at"] is not None and m["restauracao"] is None
    assert "Nada foi restaurado" in capsys.readouterr().out
    c = warehouse.connect()
    try:
        assert c.execute("SELECT count(*) FROM gold.campaign_daily").fetchone()[0] > 0, "o lake nunca fica vazio"
        assert c.execute("SELECT count(*) FROM ops.lake_restores").fetchone()[0] == 0 if c.execute(
            "SELECT count(*) FROM information_schema.tables WHERE table_catalog='ops' AND table_name='lake_restores'"
        ).fetchone()[0] else True
    finally:
        c.close()
