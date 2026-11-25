"""Fase 3 — traces da trilha stack (specs/003-stack-traces-dashboards, pesquisa R2/R3).

Dois papéis:

1. **Ligar o agente à execução.** O DAG passa o contexto W3C da tarefa do Airflow no `TRACEPARENT`;
   `attach_from_env()` o torna o contexto atual. Assim os spans do agente (agentready.tracing, INALTERADO)
   nascem filhos de `worker.agente.executar` — o mesmo trace da execução, sem mudar o código do agente.
2. **Spans de domínio do pipeline** (lote, veredito, resultado do agente, resumo) num `TracerProvider`
   PRÓPRIO, que só exporta por OTLP. Ele nunca vira o provider global: o provider global é o do
   agentready.tracing, que também grava o log de auditoria com cadeia de hash — e span de pipeline não
   entra no registro de auditoria das decisões (FR-011).

Nada aqui pode derrubar uma tarefa: exportação, flush e consulta ao Phoenix só avisam (FR-012).
Contratos: contracts/span-catalog.md e contracts/trace-links.md.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import threading
import urllib.error
import urllib.request
from contextlib import contextmanager
from zoneinfo import ZoneInfo

from opentelemetry import context as otel_context
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor, SpanExporter
from opentelemetry.trace import Link, SpanContext, Status, StatusCode, TraceFlags
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

SERVICE_NAME = "aurora-stack"
TZ = ZoneInfo("America/Sao_Paulo")
FLUSH_TIMEOUT_MS = 3000
_log = logging.getLogger("agentready_stack.telemetry")
_lock = threading.Lock()
_provider: TracerProvider | None = None
_warned = False


class _QuietExporter(SpanExporter):
    """Envolve o exportador OTLP: erro de rede vira UM aviso em pt-BR, nunca exceção."""

    def __init__(self, inner: SpanExporter):
        self._inner = inner

    def export(self, spans):
        global _warned
        try:
            return self._inner.export(spans)
        except Exception as e:  # noqa: BLE001 - telemetria nunca derruba a tarefa
            if not _warned:
                _warned = True
                # stderr: a ÚLTIMA linha do stdout é o JSON que o DAG lê (run_stack); um aviso ali derrubaria a tarefa
                print(f"aviso: traces da stack não enviados ao coletor ({type(e).__name__}); "
                      "as decisões seguem no log de auditoria (make auditoria).", file=sys.stderr, flush=True)
            from opentelemetry.sdk.trace.export import SpanExportResult
            return SpanExportResult.FAILURE

    def shutdown(self):
        try:
            self._inner.shutdown()
        except Exception:  # noqa: BLE001
            pass

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        try:
            return self._inner.force_flush(timeout_millis)
        except Exception:  # noqa: BLE001
            return False


def _get_provider() -> TracerProvider:
    global _provider
    with _lock:
        if _provider is None:
            # shutdown_on_exit=False: o flush é explícito (flush()), com tempo limitado.
            _provider = TracerProvider(resource=Resource({"service.name": SERVICE_NAME}), shutdown_on_exit=False)
            if os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"):
                try:
                    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
                    _provider.add_span_processor(BatchSpanProcessor(_QuietExporter(OTLPSpanExporter())))
                except ImportError:
                    print("aviso: exportador OTLP ausente no venv do agente; spans da stack não serão enviados.",
                          file=sys.stderr, flush=True)
        return _provider


def configure(exporter: SpanExporter | None = None) -> TracerProvider:
    """Gancho de teste: acrescenta um exportador síncrono (ex.: InMemorySpanExporter)."""
    p = _get_provider()
    if exporter is not None:
        p.add_span_processor(SimpleSpanProcessor(exporter))
    return p


def reset_for_tests() -> None:
    """Descarta o provider (os testes recriam com outro exportador)."""
    global _provider, _warned
    with _lock:
        _provider = None
        _warned = False


def attach_from_env():
    """Torna o TRACEPARENT (se houver) o contexto atual deste processo. Devolve o token do attach
    (para `detach`, usado nos testes) ou None. Nunca levanta exceção."""
    tp = os.environ.get("TRACEPARENT")
    if not tp:
        return None
    try:
        ctx = TraceContextTextMapPropagator().extract({"traceparent": tp})
        if not trace.get_current_span(ctx).get_span_context().is_valid:
            return None
        return otel_context.attach(ctx)
    except Exception:  # noqa: BLE001
        return None


def detach(token) -> None:
    if token is not None:
        try:
            otel_context.detach(token)
        except Exception:  # noqa: BLE001
            pass


def _value(v):
    """Mesma convenção do agentready.tracing: escalar como está; o resto vira JSON. None é OMITIDO
    (desconhecido nunca vira 0 nem "null" nos spans da stack — Princípio III)."""
    if isinstance(v, (str, bool, int, float)):
        return v
    return json.dumps(v, ensure_ascii=False, default=str)


def set_attrs(sp, **attrs) -> None:
    for k, v in attrs.items():
        if v is not None:
            sp.set_attribute(k, _value(v))


@contextmanager
def span(name: str, *, error: str | None = None, links: list[Link] | None = None, **attrs):
    """Span de domínio da stack (filho do contexto atual). `error` = status ERROR com mensagem pt-BR.
    Se a criação do span falhar por qualquer motivo, o bloco roda mesmo assim (span inerte)."""
    # O span só nasce no __enter__ (start_as_current_span é preguiçoso): a criação E a montagem ficam no try.
    try:
        tracer = _get_provider().get_tracer("agentready_stack")
        cm = tracer.start_as_current_span(name, links=links or None)
        sp = cm.__enter__()
    except Exception:  # noqa: BLE001
        yield trace.INVALID_SPAN
        return
    try:
        try:
            set_attrs(sp, **attrs)
            if error:
                sp.set_status(Status(StatusCode.ERROR, error))
        except Exception:  # noqa: BLE001 - atributo ruim nunca derruba a tarefa
            pass
        yield sp
    except BaseException as e:
        try:
            suppress = cm.__exit__(type(e), e, e.__traceback__)
        except Exception:  # noqa: BLE001
            suppress = False
        if not suppress:
            raise
    else:
        try:
            cm.__exit__(None, None, None)
        except Exception:  # noqa: BLE001
            pass


def fail(sp, message: str) -> None:
    sp.set_status(Status(StatusCode.ERROR, message))


def link_to(trace_id: str, span_id: str) -> Link:
    ctx = SpanContext(trace_id=int(trace_id, 16), span_id=int(span_id, 16), is_remote=True,
                      trace_flags=TraceFlags(TraceFlags.SAMPLED))
    return Link(ctx)


def business_date(reference_ts: str | None = None) -> str:
    from datetime import datetime
    if reference_ts:
        try:
            return datetime.fromisoformat(reference_ts).date().isoformat()
        except ValueError:
            pass
    return datetime.now(TZ).date().isoformat()


def common_attrs(dag_run_id: str | None, business_date_: str | None = None, incident: str | None = None) -> dict:
    """Atributos comuns de todo span da seção B do catálogo (contracts/span-catalog.md)."""
    return {"airflow.dag_run.run_id": dag_run_id, "agentready.business_date": business_date_ or business_date(),
            "agentready.incident": incident or "nenhum"}


def run_attrs(dag_run_id: str | None = None) -> dict:
    """Atributos comuns a partir do ambiente que o DAG passa (STACK_DAG_RUN_ID, STACK_INCIDENT)."""
    return common_attrs(dag_run_id or os.environ.get("STACK_DAG_RUN_ID"), None,
                        os.environ.get("STACK_INCIDENT") or "nenhum")


def _base() -> str:
    return f"http://localhost:{os.environ.get('PHOENIX_PORT') or '6006'}"


def trace_url(trace_id: str | None) -> str | None:
    return f"{_base()}/redirects/traces/{trace_id}" if trace_id else None


def span_url(span_id: str | None) -> str | None:
    return f"{_base()}/redirects/spans/{span_id}" if span_id else None


def flush() -> None:
    """Esvazia os dois provedores (o da stack e o do agentready.tracing) com tempo limitado."""
    try:
        if _provider is not None:
            _provider.force_flush(FLUSH_TIMEOUT_MS)
    except Exception:  # noqa: BLE001
        pass
    try:
        from agentready import tracing
        if tracing._provider is not None:  # noqa: SLF001 - leitura apenas, para limitar o tempo
            tracing._provider.force_flush(FLUSH_TIMEOUT_MS)  # noqa: SLF001
    except Exception:  # noqa: BLE001
        pass


# ------------------------------------------------------------------ verificação no Phoenix (US3)

def _post_json(url: str, body: dict, timeout: float) -> dict:
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def collector_up(timeout: float = 2) -> bool:
    url = os.environ.get("OTEL_COLLECTOR_HEALTH_URL", "http://otel-collector:13133/")
    try:
        with urllib.request.urlopen(url, timeout=timeout):
            return True
    except Exception:  # noqa: BLE001
        return False


def phoenix_has_trace(trace_id: str, attempts: int = 6, wait_s: float = 5, timeout: float = 3,
                      need: str = "agent.run") -> dict:
    """A árvore do agente (span `need`) já está no Phoenix? Tenta por ~30 s (SC-004). Nunca levanta exceção.
    O trace é o da execução inteira: outros spans dela (pipeline, Airflow) podem ter chegado sem o do agente,
    então a checagem exige o span `need`, não só o trace. Devolve {"ok": bool, "reason": pt-BR, "url": link}."""
    import time
    base = os.environ.get("PHOENIX_INTERNAL_URL", "http://phoenix:6006").rstrip("/")
    query = {"query": "query($t: String!) { getTraceByOtelId(traceId: $t) { spans(first: 1000) "
                      "{ edges { node { name } } } } }", "variables": {"t": trace_id}}
    reachable = False
    for i in range(max(1, attempts)):
        try:
            data = _post_json(f"{base}/graphql", query, timeout)
            reachable = True
            t = (data.get("data") or {}).get("getTraceByOtelId")
            if t and any(e["node"]["name"] == need for e in (t.get("spans") or {}).get("edges", [])):
                return {"ok": True, "reason": "", "url": trace_url(trace_id)}
        except Exception:  # noqa: BLE001
            pass
        if i < attempts - 1:
            time.sleep(wait_s)
    if not collector_up():
        reason = "coletor fora do ar; os spans desta execução não chegam ao Phoenix"
    elif reachable:
        reason = "o Phoenix responde, mas a árvore do agente ainda não chegou"
    else:
        reason = "Phoenix fora do ar; os spans estão na fila do coletor e serão entregues quando ele voltar"
    return {"ok": False, "reason": reason, "url": trace_url(trace_id)}
