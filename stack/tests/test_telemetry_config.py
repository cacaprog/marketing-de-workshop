"""Fase 3 (FR-001, FR-017): configuração dos traces — compose, coletor e banco do Phoenix.

Só lê arquivos (roda no venv do agente). A validação do coletor pelo próprio binário roda no `make test`
(`otelcol-contrib validate`), porque a imagem do coletor não é a da stack.
"""
from __future__ import annotations

from pathlib import Path

import yaml

STACK = Path(__file__).resolve().parents[1]


def _compose() -> dict:
    return yaml.safe_load((STACK / "compose.yaml").read_text())


def test_services_and_ports():
    svc = _compose()["services"]
    assert "otel-collector" in svc and "phoenix" in svc and "db-init" in svc
    assert "marquez-db-init" not in svc
    assert "ports" not in svc["otel-collector"], "o coletor não publica porta no host"
    assert svc["phoenix"]["ports"] == ["${PHOENIX_PORT:-6006}:6006"]
    assert svc["otel-collector"]["image"] == "otel/opentelemetry-collector-contrib:0.166.0"
    assert svc["phoenix"]["image"].startswith("arizephoenix/phoenix:version-")
    assert svc["marquez-api"]["depends_on"] == {"db-init": {"condition": "service_completed_successfully"}}


def test_phoenix_offline_and_local_only():
    env = _compose()["services"]["phoenix"]["environment"]
    assert env["PHOENIX_TELEMETRY_ENABLED"] == "false"
    assert env["PHOENIX_ALLOW_EXTERNAL_RESOURCES"] == "false"
    assert env["PHOENIX_DISABLE_MODEL_COST_AUTO_UPDATE"] == "true"
    assert env["PHOENIX_DISABLE_AGENT_ASSISTANT"] == "true"
    assert env["PHOENIX_ENABLE_AUTH"] == "false"
    assert env["PHOENIX_SQL_DATABASE_URL"].endswith("@postgres:5432/phoenix")


def test_airflow_telemetry_env():
    env = _compose()["x-airflow-common"]["environment"]
    assert env["AIRFLOW__TRACES__OTEL_ON"] == "True"
    assert env["AIRFLOW__TRACES__TASK_RUNNER_FLUSH_TIMEOUT_MILLISECONDS"] == "3000"
    assert env["OTEL_EXPORTER_OTLP_ENDPOINT"] == "http://otel-collector:4318"
    assert env["OTEL_EXPORTER_OTLP_PROTOCOL"] == "http/protobuf"
    assert env["OTEL_TRACES_EXPORTER"] == "otlp_proto_http"
    assert float(env["OTEL_EXPORTER_OTLP_TIMEOUT"]) <= 5
    assert env["OTEL_SERVICE_NAME"] == "airflow"
    assert env["PHOENIX_PORT"] == "${PHOENIX_PORT:-6006}"


def test_collector_pipeline():
    cfg = yaml.safe_load((STACK / "config" / "otel-collector.yaml").read_text())
    upserts = cfg["processors"]["resource"]["attributes"]
    assert {"key": "openinference.project.name", "value": "aurora", "action": "upsert"} in upserts
    exporter = cfg["exporters"]["otlp_http"]
    assert exporter["endpoint"] == "http://phoenix:6006"
    assert exporter["sending_queue"] == {"enabled": True, "storage": "file_storage"}
    assert exporter["retry_on_failure"]["enabled"] is True
    stmts = " ".join(cfg["processors"]["transform"]["trace_statements"][0]["statements"])
    for kind in ("CHAIN", "AGENT", "TOOL", "LLM", "RETRIEVER"):
        assert f'"{kind}"' in stmts
    pipe = cfg["service"]["pipelines"]["traces"]
    assert pipe["processors"] == ["memory_limiter", "resource", "transform", "batch"]
    assert set(cfg["service"]["extensions"]) == {"health_check", "file_storage"}


def test_phoenix_db_init_is_idempotent():
    sql = (STACK / "postgres-init" / "02-phoenix.sql").read_text()
    assert "WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'phoenix')" in sql
    assert "WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'phoenix')" in sql
