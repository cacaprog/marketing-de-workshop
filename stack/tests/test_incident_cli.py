"""Ciclo de vida do incidente na trilha stack (Fase 2, pesquisa R8): detectar, resolver, revelar, listar.

`resolver` restaura a Bronze pelas funções compartilhadas e NUNCA roda o pipeline da trilha padrão:
quem reconstrói as camadas é o DAG (o Makefile dispara uma execução depois).
"""
import json

import pytest

from agentready.db import connect

from agentready_stack import cli, tasks


def _silver_fingerprint():
    c = connect()
    try:
        return c.execute("SELECT COUNT(*), string_agg(DISTINCT batch_id, ',' ORDER BY batch_id) "
                         "FROM silver.conversions").fetchone()
    finally:
        c.close()


def _last_json(capsys):
    return json.loads(capsys.readouterr().out.strip().splitlines()[-1])


def test_lifecycle_list_detect_reveal_resolve(built, capsys):
    tasks.ingest({"incident": "centavos"})
    capsys.readouterr()

    assert cli.main(["incident", "list"]) == 0
    listed = _last_json(capsys)
    open_ = [i for i in listed["incidents"] if i["resolved_at"] is None]
    assert len(open_) == 1 and open_[0]["kind"] == "centavos"

    assert cli.main(["incident", "detect"]) == 0
    assert _last_json(capsys)["detected_at"] is not None

    assert cli.main(["incident", "reveal"]) == 0
    assert "CENTAVOS" in capsys.readouterr().out

    c = connect()
    redelivered = c.execute("SELECT COUNT(*) FROM bronze.conversions WHERE batch_id LIKE '%-redelivery'").fetchone()[0]
    c.close()
    assert redelivered > 0
    before = _silver_fingerprint()

    assert cli.main(["incident", "resolve"]) == 0
    out = capsys.readouterr().out
    res = json.loads(out.strip().splitlines()[-1])
    assert res["resolved_at"] is not None and res["TTR_min"] is not None
    assert "TTD" in out and "TTR" in out

    c = connect()
    try:
        assert c.execute("SELECT COUNT(*) FROM bronze.conversions WHERE batch_id LIKE '%-redelivery'").fetchone()[0] == 0
        assert c.execute("SELECT COUNT(*) FROM bronze.conversions WHERE batch_id = ?",
                         [open_[0]["batch_id"]]).fetchone()[0] > 0, "o lote original volta para a Bronze"
    finally:
        c.close()
    assert _silver_fingerprint() == before, "resolver não pode reconstruir camadas (isso é papel do DAG)"


def test_detect_without_open_incident_is_a_clear_failure(built, capsys):
    assert cli.main(["incident", "detect"]) == 1
    assert "nenhum incidente aberto" in capsys.readouterr().err


def test_decisions_since_lists_changes_and_queue_with_trace(built, capsys):
    from datetime import datetime, timedelta

    from agentready_stack import tasks
    since = (datetime.now() - timedelta(minutes=1)).replace(microsecond=0).isoformat()
    out = tasks.run_agent("rules", False, "run-decisoes")
    capsys.readouterr()
    assert cli.main(["decisions", "--since", since]) == 0
    printed = capsys.readouterr().out
    res = json.loads(printed.strip().splitlines()[-1])
    assert res["decisions"], "o agente da manhã executa ou enfileira algo"
    assert all(d["trace_id"] == out["trace_id"] for d in res["decisions"])
    assert "/lineage/job/aurora/aurora_midia_diario.agente.executar" in res["lineage_link"]
    assert "candidatas a rollback" in printed


def test_close_run_warns_when_lineage_is_down(built, monkeypatch, capsys):
    """FR-013: Marquez fora do ar não falha a execução; o fechamento registra um aviso visível."""
    from agentready_stack import tasks
    monkeypatch.setenv("MARQUEZ_URL", "http://127.0.0.1:9")
    res = tasks.close_run("run-sem-linhagem")
    assert res["lineage"]["ok"] is False
    assert "linhagem indisponível" in capsys.readouterr().out


def test_decisions_since_accepts_stage_friendly_times(built, capsys):
    """Achado do ensaio do Bloco 5: o horário do `listar` tinha espaço e HH:MM dava traceback."""
    from datetime import date, datetime

    from agentready_stack import incidents_cli, tasks
    c = connect()
    try:
        assert incidents_cli.parse_since(c, "14:03") == datetime.combine(date.today(), datetime.strptime("14:03", "%H:%M").time())
        assert incidents_cli.parse_since(c, "2026-11-25 14:03:29") == datetime(2026, 11, 25, 14, 3, 29)
        assert incidents_cli.parse_since(c, "2026-11-25T14:03:29") == datetime(2026, 11, 25, 14, 3, 29)
        with pytest.raises(ValueError, match="horário inválido"):
            incidents_cli.parse_since(c, "ontem")
    finally:
        c.close()
    tasks.ingest({"incident": "feed_parado"})
    c = connect()
    try:
        injected = c.execute("SELECT max(injected_at) FROM ops.incidents").fetchone()[0]
        assert incidents_cli.parse_since(c, "") == injected, "vazio = desde a injeção do último incidente"
    finally:
        c.close()
    capsys.readouterr()
    assert cli.main(["decisions", "--since", "ontem"]) == 1
    assert "horário inválido" in capsys.readouterr().err
