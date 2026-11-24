# Imagem da trilha stack: Airflow 3.3 + três venvs isolados (dbt, datacontract-cli, agente).
# Contexto de build = raiz do repositório (veja compose.yaml), para instalar o agentready.
# Em tempo de execução a raiz do repo é montada SOMENTE LEITURA em /opt/agentready, então
# o agente, os contratos e a config são exatamente os arquivos do repositório (sem cópias).
FROM apache/airflow:3.3.2-python3.12

ARG AIRFLOW_VERSION=3.3.2
ARG PYTHON_VERSION=3.12

# uv fixado: cria e sincroniza os venvs a partir dos locks em stack/requirements/.
COPY --from=ghcr.io/astral-sh/uv:0.11.21 /uv /usr/local/bin/uv

USER root
RUN mkdir -p /opt/venvs /opt/agentready /opt/stack-data /opt/dbt /opt/dbt_deps_build \
 && chown -R airflow: /opt/venvs /opt/agentready /opt/stack-data /opt/dbt /opt/dbt_deps_build
USER airflow

# 1) Ambiente do Airflow: Cosmos (dbt como tasks) + pytest (teste de integridade do DAG).
#    uv instala DENTRO do venv do Airflow (/home/airflow/.local) sem reinstalar o Airflow: um `pip install`
#    aqui reescrevia o shebang do comando `airflow` e quebrava a execução com UID arbitrário.
RUN uv pip install --python /home/airflow/.local/bin/python "apache-airflow==${AIRFLOW_VERSION}" \
      "astronomer-cosmos~=1.14" "pytest>=8" && head -1 /home/airflow/.local/bin/airflow

# 2) Venvs isolados, sincronizados com os locks (pesquisa R10).
COPY --chown=airflow stack/requirements/ /opt/requirements/
RUN set -eux; \
    for v in dbt dcc agent; do uv venv --python "/usr/python/bin/python${PYTHON_VERSION}" "/opt/venvs/$v"; \
      uv pip sync --python "/opt/venvs/$v/bin/python" "/opt/requirements/$v.txt"; done

# 3) Código do repositório, instalado em modo editável (o mount de execução substitui estes arquivos).
COPY --chown=airflow pyproject.toml README.md /opt/agentready/
COPY --chown=airflow src/ /opt/agentready/src/
COPY --chown=airflow stack/agentready_stack/ /opt/agentready/stack/agentready_stack/
RUN set -eux; \
    uv pip install --python /opt/venvs/agent/bin/python --no-deps -e /opt/agentready -e /opt/agentready/stack/agentready_stack; \
    uv pip install --python /opt/venvs/dbt/bin/python --no-deps -e /opt/agentready -e /opt/agentready/stack/agentready_stack

# 4) Pacotes dbt dos testes gerados (dbt_utils, dbt_expectations), baixados no build para rodar offline.
COPY --chown=airflow stack/dbt/aurora/dbt_project.yml stack/dbt/aurora/packages.yml /opt/dbt_deps_build/
RUN cd /opt/dbt_deps_build && /opt/venvs/dbt/bin/dbt deps --project-dir . --profiles-dir . && ls /opt/dbt/packages

ENV AGENTREADY_HOME=/opt/agentready \
    AGENTREADY_DB=/opt/stack-data/warehouse.duckdb \
    AGENTREADY_TRACES=/opt/stack-data/traces \
    DBT_PROJECT_DIR=/opt/airflow/dbt/aurora \
    DBT_PROFILES_DIR=/opt/airflow/dbt/aurora
