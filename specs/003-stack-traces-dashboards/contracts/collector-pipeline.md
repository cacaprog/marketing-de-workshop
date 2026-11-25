# Contract: Collector Pipeline and Telemetry Environment

## Services (compose additions)

| Service | Image | Host port | Depends on | Health |
|---|---|---|---|---|
| `otel-collector` | `otel/opentelemetry-collector-contrib:0.166.0` | none (internal 4318, 13133) | — | `health_check` extension on :13133 |
| `phoenix` | `arizephoenix/phoenix:version-22.0.1-nonroot` | `${PHOENIX_PORT:-6006}:6006` | `db-init` completed | HTTP GET `/` |
| `db-init` (renamed from `marquez-db-init`) | `postgres:16` | — | `postgres` healthy | one-off. Runs every `postgres-init/*.sql` in order, idempotently |

`marquez-api` now depends on `db-init`. The rename is internal: no user command names it.

## Collector config (`stack/config/otel-collector.yaml`, behavior)

```text
receivers:   otlp (protocols.http on 0.0.0.0:4318)
processors:  memory_limiter (limit 256 MiB) → resource (upsert openinference.project.name=aurora)
             → transform (span kind table, span-catalog §D) → batch
exporters:   OTLP/HTTP → http://phoenix:6006  (sending_queue: storage=file_storage, persistent;
             retry_on_failure: enabled, max_elapsed_time 2h)
extensions:  health_check, file_storage (directory /var/lib/otelcol/queue → ./data/otel-queue)
service.pipelines.traces: otlp → [memory_limiter, resource, transform, batch] → exporter
```

The exporter **component name** is whatever 0.166.0 documents (the 0.144 rename). `test_telemetry_config.py`
runs `otelcol-contrib validate --config` in the collector image, so a wrong name fails the build, not the
workshop.

## Environment (airflow-common, so every Airflow process and every `agentready-stack` subprocess)

| Variable | Value | Effect |
|---|---|---|
| `AIRFLOW__TRACES__OTEL_ON` | `True` | Airflow emits `dag_run.*` and `worker.*` spans (R1) |
| `AIRFLOW__TRACES__TASK_RUNNER_FLUSH_TIMEOUT_MILLISECONDS` | `3000` | bounded flush at task exit if the collector is down |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | `http://otel-collector:4318` | Airflow, the stack tracer, and the shared `tracing.init()` OTLP branch |
| `OTEL_EXPORTER_OTLP_PROTOCOL` | `http/protobuf` | one protocol everywhere |
| `OTEL_EXPORTER_OTLP_TIMEOUT` | small (value fixed in the spike: the Python SDK's unit is checked, not assumed) | fail fast when the collector is down |
| `OTEL_SERVICE_NAME` | `airflow` | stripped from the subprocess env by `run_stack` (the agent sets its own `service.name`; the stack tracer sets `aurora-stack`) |
| `PHOENIX_PORT` | `${PHOENIX_PORT:-6006}` | used by the link builder |
| `TRACEPARENT` | set **per subprocess** by `run_stack` | parent context for the stack tracer and the agent (R2) |

**`make test` and `make parity`** set `OTEL_EXPORTER_OTLP_ENDPOINT=` (empty), so they never wait on a collector
and never put test or parity spans into Phoenix's `aurora` project. Other one-off commands keep the compose
environment, because `make rollback` must export its `humano.rollback` span. Unit tests that check emitted spans use
an in-memory exporter on the stack tracer. The live checks are in `make test-live`.
