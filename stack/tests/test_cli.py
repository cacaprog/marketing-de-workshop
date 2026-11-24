"""CLI agentready-stack: erros de ambiente claros (contracts/commands.md: código 2) e doctor."""
import os
import subprocess
import sys
import time

from agentready.db import connect


def test_lock_conflict_gives_exit_2_and_ptbr_message(built, tmp_path):
    db = os.environ["AGENTREADY_DB"]
    c = connect()
    c.close()                                   # garante que o arquivo existe com os schemas
    holder = subprocess.Popen([sys.executable, "-c",
                               "import duckdb,sys,time; c=duckdb.connect(sys.argv[1]); print('ok', flush=True); time.sleep(60)", db],
                              stdout=subprocess.PIPE, text=True)
    try:
        assert holder.stdout.readline().strip() == "ok"
        t0 = time.time()
        r = subprocess.run([sys.executable, "-m", "agentready_stack.cli", "task", "close"],
                           capture_output=True, text=True, env=os.environ | {"AGENTREADY_DB": db}, timeout=60)
        assert r.returncode == 2, (r.returncode, r.stderr[-800:])
        assert "aberto por outro processo" in r.stderr
        assert time.time() - t0 < 30, "tem de falhar rápido, sem travar"
    finally:
        holder.kill()


def test_doctor_requires_matching_duckdb(monkeypatch, capsys):
    from agentready_stack import cli
    monkeypatch.setattr(cli.os.path, "exists", lambda p: True)
    fake = {"dbt": {"duckdb": "2.0.1", "dbt-core": "1", "dbt-duckdb": "1"},
            "agente": {"duckdb": "1.5.0", "mcp": "2", "anthropic": "2"},
            "datacontract": {"datacontract-cli": "1"}, "airflow": {"apache-airflow": "3", "astronomer-cosmos": "1"}}
    monkeypatch.setattr(cli, "_versions", lambda python, pk: fake[next(k for k, v in cli.VENVS.items() if v == python)])
    assert cli.main(["doctor"]) == 1
    assert "DuckDB difere" in capsys.readouterr().err
