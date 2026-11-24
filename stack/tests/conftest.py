"""Testes da trilha stack: warehouse temporário + dbt de verdade (subprocesso no venv do dbt).

No container: `make test`. Localmente (sem Docker), aponte as variáveis para seus venvs:
  STACK_DBT_BIN=.../bin/dbt  DBT_PACKAGES_DIR=...  STACK_DATACONTRACT_BIN=.../bin/datacontract
"""
import os
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path

_tmp = tempfile.mkdtemp(prefix="agentready-stack-test-")
os.environ["AGENTREADY_DB"] = os.path.join(_tmp, "stack.duckdb")
os.environ["AGENTREADY_TRACES"] = os.path.join(_tmp, "traces")

import pytest  # noqa: E402

STACK_DIR = Path(__file__).resolve().parents[1]
DBT_BIN = os.environ.get("STACK_DBT_BIN", "/opt/venvs/dbt/bin/dbt")
DBT_PROJECT = Path(os.environ.get("STACK_DBT_PROJECT", "/opt/airflow/dbt/aurora"))
if not DBT_PROJECT.exists():
    DBT_PROJECT = STACK_DIR / "dbt" / "aurora"
DCC_BIN = os.environ.get("STACK_DATACONTRACT_BIN", "/opt/venvs/dcc/bin/datacontract")

# Horário de referência fixo: frescor e paridade não dependem de quando o teste roda.
REF = datetime.now().replace(minute=0, second=0, microsecond=0)


def run_dbt(command: str = "build", select: str | None = None, vars_: dict | None = None) -> subprocess.CompletedProcess:
    args = [DBT_BIN, command, "--project-dir", str(DBT_PROJECT), "--profiles-dir", str(DBT_PROJECT)]
    if select:
        args += ["--select", select]
    v = {"reference_ts": REF.isoformat()} | (vars_ or {})
    args += ["--vars", "{" + ", ".join(f"{k}: '{val}'" for k, val in v.items()) + "}"]
    env = os.environ | {"DBT_TARGET_PATH": os.path.join(_tmp, "dbt_target"), "DBT_LOG_PATH": os.path.join(_tmp, "dbt_logs")}
    return subprocess.run(args, capture_output=True, text=True, env=env, timeout=600)


@pytest.fixture(scope="session", autouse=True)
def contract_tests_generated():
    """Gera os testes dbt dos contratos (arquivos não versionados), como o airflow-init faz."""
    if Path(DCC_BIN).exists():
        env = os.environ | {"DATACONTRACT_BIN": DCC_BIN}
        subprocess.run([str(STACK_DIR / "scripts" / "contracts-sync.sh"), str(STACK_DIR.parent / "contracts"),
                        str(DBT_PROJECT / "models" / "silver")], check=True, capture_output=True, env=env)


@pytest.fixture
def dbt():
    """Roda o dbt contra o warehouse temporário; falha o teste com a saída do dbt se der erro."""
    def _run(select: str | None = None, vars_: dict | None = None, expect_ok: bool = True):
        r = run_dbt("build", select, vars_)
        if expect_ok and r.returncode != 0:
            pytest.fail(f"dbt build falhou:\n{r.stdout[-4000:]}\n{r.stderr[-2000:]}")
        return r
    return _run


@pytest.fixture
def scenario():
    """Gera o cenário da Aurora (Bronze + estado operacional) no horário de referência."""
    from agentready import generate

    def _gen(now: datetime = REF):
        return generate.generate(now)
    return _gen


@pytest.fixture
def built(scenario, dbt):
    """Cenário da manhã + todas as camadas construídas pelo dbt."""
    scenario()
    dbt()
    return REF


@pytest.fixture
def con(built):
    from agentready.db import connect
    c = connect()
    yield c
    c.close()
