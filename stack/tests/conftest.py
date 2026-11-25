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


# ---------------------------------------------------------------- Fase 2 (observabilidade e linhagem)

@pytest.fixture
def run_incident(scenario, dbt):
    """Cenário da manhã → build → incidente injetado (como o lote reenviado de ontem) → build.

    `breaker` liga o disjuntor de distribuição só nesta construção (o mesmo que o override do DAG)."""
    from agentready import incidents
    from agentready.db import connect

    def _run(kind: str, breaker: bool = False, extra_vars: dict | None = None):
        v = {"block_on_distribution_anomaly": str(breaker).lower()} | (extra_vars or {})
        scenario()
        dbt(vars_=v)
        c = connect()
        try:
            incidents.inject(c, kind)
        finally:
            c.close()
        return dbt(vars_=v, expect_ok=False)
    return _run


@pytest.fixture
def short_history(scenario):
    """Cenário com só os 3 últimos dias de conversões na Bronze: linha de base insuficiente (pesquisa R7)."""
    from agentready.db import connect
    scenario()
    c = connect()
    try:
        c.execute("DELETE FROM bronze.conversions WHERE TRY_CAST(converted_at AS DATE) < current_date - 3")
    finally:
        c.close()
    return REF


@pytest.fixture
def marquez():
    """URL da API do Marquez (só nos testes ao vivo: `make test-live`)."""
    import urllib.request
    url = os.environ.get("MARQUEZ_URL", "http://marquez-api:5000")
    try:
        urllib.request.urlopen(f"{url}/api/v1/namespaces", timeout=5).read()
    except OSError:
        pytest.skip("Marquez indisponível: rode `make test-live` com a stack no ar")
    return url


@pytest.fixture(scope="session", autouse=True)
def _parity_sides_cache():
    """Cada lado da paridade (gerar + construir + agente) roda UMA vez por sessão, mesmo que o arquivo da
    Fase 1 e o da Fase 2 peçam o mesmo cenário. A chave inclui STACK_PARITY_EXTRA_VARS (teste de deriva)."""
    import copy
    try:
        from agentready_stack import parity
    except ImportError:          # testes de integridade do DAG rodam no Python do Airflow, sem o pacote
        yield
        return
    original, cache = parity.run_side, {}

    def cached(track, scenario, ref):
        key = (track, scenario, ref.isoformat(), os.environ.get("STACK_PARITY_EXTRA_VARS"))
        if key not in cache:
            cache[key] = original(track, scenario, ref)
        return copy.deepcopy(cache[key])
    parity.run_side = cached
    yield
    parity.run_side = original
