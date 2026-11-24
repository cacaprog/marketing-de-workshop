"""Linhagem agêntica com OpenTelemetry.

Cada decisão do agente vira uma árvore de spans: quais fontes leu, qual versão do
contrato/modelo semântico valia, quais pré-condições passaram ou falharam e por quê.

Os spans vão para traces/audit.jsonl, um log com encadeamento de hash (cada
registro carrega o hash do anterior), o que torna evidente qualquer adulteração.
Se OTEL_EXPORTER_OTLP_ENDPOINT estiver definido e o pacote opcional 'otlp' estiver
instalado, os mesmos spans também seguem para Arize Phoenix / Langfuse / Jaeger.
"""
from __future__ import annotations

import hashlib
import html
import json
import os
from contextlib import contextmanager
from datetime import datetime, timezone

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor, SpanExporter, SpanExportResult
from opentelemetry.trace import Status, StatusCode

from agentready.settings import TRACES_DIR

AUDIT_LOG = TRACES_DIR / "audit.jsonl"
GENESIS = "0" * 64
_provider: TracerProvider | None = None


def _last_hash() -> str:
    if not AUDIT_LOG.exists():
        return GENESIS
    lines = AUDIT_LOG.read_text(encoding="utf-8").splitlines()
    return json.loads(lines[-1])["hash"] if lines else GENESIS


def _ts(ns: int | None) -> str | None:
    return datetime.fromtimestamp(ns / 1e9, tz=timezone.utc).isoformat() if ns else None


class HashChainJsonlExporter(SpanExporter):
    def export(self, spans) -> SpanExportResult:
        TRACES_DIR.mkdir(parents=True, exist_ok=True)
        prev = _last_hash()
        with open(AUDIT_LOG, "a", encoding="utf-8") as f:
            for s in spans:
                rec = {
                    "trace_id": f"{s.context.trace_id:032x}",
                    "span_id": f"{s.context.span_id:016x}",
                    "parent_span_id": f"{s.parent.span_id:016x}" if s.parent else None,
                    "name": s.name,
                    "start_time": _ts(s.start_time),
                    "end_time": _ts(s.end_time),
                    "status": s.status.status_code.name,
                    "status_message": s.status.description,
                    "attributes": dict(s.attributes or {}),
                    "events": [{"name": e.name, "time": _ts(e.timestamp), "attributes": dict(e.attributes or {})}
                               for e in s.events],
                    "prev_hash": prev,
                }
                rec["hash"] = hashlib.sha256(json.dumps(rec, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
                prev = rec["hash"]
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        return SpanExportResult.SUCCESS


def init() -> TracerProvider:
    global _provider
    if _provider:
        return _provider
    _provider = TracerProvider(resource=Resource.create({"service.name": "agente-orcamento-midia",
                                                          "deployment.environment": "workshop"}))
    _provider.add_span_processor(SimpleSpanProcessor(HashChainJsonlExporter()))
    if os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"):
        try:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
            _provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
        except ImportError:
            print("aviso: OTEL_EXPORTER_OTLP_ENDPOINT definido mas pacote otlp ausente (uv pip install -e '.[otlp]')")
    trace.set_tracer_provider(_provider)
    return _provider


def flush() -> None:
    if _provider:
        _provider.force_flush()


def _attr(v):
    if isinstance(v, (str, bool, int, float)):
        return v
    if v is None:
        return "null"
    return json.dumps(v, ensure_ascii=False, default=str)


@contextmanager
def span(name: str, **attrs):
    init()
    with trace.get_tracer("agentready").start_as_current_span(name) as sp:
        for k, v in attrs.items():
            sp.set_attribute(k, _attr(v))
        try:
            yield sp
        except Exception as e:
            sp.set_status(Status(StatusCode.ERROR, str(e)))
            raise


def set_attrs(sp, **attrs) -> None:
    for k, v in attrs.items():
        sp.set_attribute(k, _attr(v))


def fail(sp, message: str) -> None:
    sp.set_status(Status(StatusCode.ERROR, message))


def current_trace_id() -> str | None:
    ctx = trace.get_current_span().get_span_context()
    return f"{ctx.trace_id:032x}" if ctx.is_valid else None


# ---------- leitura / auditoria ----------

def load(trace_id: str | None = None) -> list[dict]:
    if not AUDIT_LOG.exists():
        return []
    recs = [json.loads(line) for line in AUDIT_LOG.read_text(encoding="utf-8").splitlines() if line.strip()]
    if trace_id == "last" and recs:
        trace_id = recs[-1]["trace_id"]
    return [r for r in recs if trace_id is None or r["trace_id"].startswith(trace_id)]


def trace_ids() -> list[tuple[str, str, str]]:
    roots = [r for r in load() if r["parent_span_id"] is None]
    return [(r["trace_id"], r["name"], r["start_time"]) for r in roots]


def verify_chain(recs: list[dict] | None = None) -> tuple[bool, int, str]:
    prev = GENESIS
    recs = load() if recs is None else recs
    for i, r in enumerate(recs):
        body = {k: v for k, v in r.items() if k != "hash"}
        if r["prev_hash"] != prev:
            return False, i, f"registro {i}: elo quebrado (prev_hash não confere)"
        if hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest() != r["hash"]:
            return False, i, f"registro {i}: conteúdo alterado ({r['name']})"
        prev = r["hash"]
    return True, len(recs), "cadeia íntegra"


def tree(spans: list[dict]) -> list[dict]:
    by_parent: dict[str | None, list[dict]] = {}
    ids = {s["span_id"] for s in spans}
    for s in sorted(spans, key=lambda s: s["start_time"]):
        parent = s["parent_span_id"] if s["parent_span_id"] in ids else None
        by_parent.setdefault(parent, []).append(s)

    def build(s):
        return {**s, "children": [build(c) for c in by_parent.get(s["span_id"], [])]}
    return [build(r) for r in by_parent.get(None, [])]


def render_html(trace_id: str) -> str:
    spans = load(trace_id)
    if not spans:
        raise ValueError(f"trace {trace_id} não encontrado")
    tid = spans[0]["trace_id"]

    def node(s) -> str:
        err = s["status"] == "ERROR"
        attrs = "".join(f"<tr><th>{html.escape(k)}</th><td>{html.escape(str(v))}</td></tr>"
                        for k, v in s["attributes"].items())
        msg = f"<div class='err'>{html.escape(s['status_message'] or '')}</div>" if err else ""
        kids = "".join(node(c) for c in s["children"])
        return (f"<details open class='{'error' if err else 'ok'}'><summary>{html.escape(s['name'])}"
                f"<span class='t'>{s['start_time'][11:23]}</span></summary>{msg}"
                f"<table>{attrs}</table>{kids}</details>")

    body = "".join(node(r) for r in tree(spans))
    return f"""<!doctype html><html lang="pt-br"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Trace {tid[:8]}</title>
<style>
:root{{--bg:#fbfaf7;--fg:#1d1d1b;--muted:#6b6a65;--line:#e2dfd6;--ok:#2f7d4f;--err:#b3261e;--card:#fff}}
@media (prefers-color-scheme: dark){{:root{{--bg:#191917;--fg:#ecebe6;--muted:#9d9b94;--line:#34332f;--ok:#6cc08b;--err:#f08a80;--card:#22221f}}}}
body{{background:var(--bg);color:var(--fg);font:14px/1.45 system-ui,sans-serif;margin:0;padding:24px 16px;max-width:1100px;margin:auto}}
h1{{font-size:18px}} .sub{{color:var(--muted)}}
details{{border-left:3px solid var(--ok);background:var(--card);margin:8px 0 8px 14px;padding:6px 10px;border-radius:4px}}
details.error{{border-left-color:var(--err)}} summary{{cursor:pointer;font-weight:600}}
.t{{color:var(--muted);font-weight:400;margin-left:10px;font-size:12px}} .err{{color:var(--err);margin:4px 0}}
table{{border-collapse:collapse;margin:6px 0;font-size:12.5px;width:100%;table-layout:fixed}}
th{{text-align:left;color:var(--muted);font-weight:500;width:240px;vertical-align:top;padding:2px 8px 2px 0}}
td{{font-family:ui-monospace,monospace;word-break:break-word;padding:2px 0}}
</style></head><body><h1>Árvore de decisão do agente</h1>
<div class="sub">trace_id {tid} · {len(spans)} spans · fonte: traces/audit.jsonl (cadeia de hash)</div>{body}</body></html>"""
