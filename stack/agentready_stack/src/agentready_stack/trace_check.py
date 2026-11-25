"""Fase 3 (`make test-live`): a cópia do trace do agente no Phoenix é igual à do log de auditoria?

    python -m agentready_stack.trace_check <trace_id>      → última linha: JSON {"ok", "items", "diffs"}

Lê os spans do trace no Phoenix (GraphQL), converte para o formato do log de auditoria e compara as duas
cópias com a MESMA normalização da paridade (parity.normalize_trace). Ignora o que só a cópia do Phoenix tem:
os atributos `openinference.*` que o coletor acrescenta, os que o Phoenix deriva (PHOENIX_DERIVED) e os de recurso
(contracts/trace-parity.md, "Live check"). Os eventos são comparados só pelo nome: o Phoenix não expõe
os atributos de evento pelo GraphQL.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request

from agentready import tracing

from agentready_stack import parity

# Atributos que o PRÓPRIO Phoenix deriva na ingestão (ex.: tool.name a partir de gen_ai.tool.name).
PHOENIX_DERIVED = {"tool.name"}
QUERY = """query($t: String!) { getTraceByOtelId(traceId: $t) { spans(first: 1000) { edges { node {
  name spanId parentId statusCode statusMessage startTime attributes events { name } } } } } }"""


def _flatten(d, prefix: str = "") -> dict:
    out = {}
    for k, v in (d or {}).items():
        key = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            out |= _flatten(v, key)
        else:
            out[key] = v
    return out


def phoenix_records(trace_id: str) -> list[dict]:
    base = os.environ.get("PHOENIX_INTERNAL_URL", "http://phoenix:6006").rstrip("/")
    req = urllib.request.Request(f"{base}/graphql", data=json.dumps({"query": QUERY, "variables": {"t": trace_id}}).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        body = json.load(r)
    if body.get("errors"):
        raise RuntimeError(f"Phoenix recusou a consulta: {body['errors'][0].get('message')}")
    data = body["data"]["getTraceByOtelId"]
    if not data:
        return []
    recs = []
    for e in data["spans"]["edges"]:
        n = e["node"]
        attrs = n["attributes"]
        attrs = json.loads(attrs) if isinstance(attrs, str) else (attrs or {})
        attrs = {k: v for k, v in _flatten(attrs).items()
                 if not k.startswith("openinference.") and k not in PHOENIX_DERIVED}
        recs.append({"span_id": n["spanId"], "parent_span_id": n["parentId"], "name": n["name"],
                     "start_time": n["startTime"], "status": n["statusCode"], "status_message": n["statusMessage"] or None,
                     "attributes": attrs, "events": [{"name": ev["name"]} for ev in n["events"] or []]})
    return recs


def _comparable(normalized: list[list]) -> list[list]:
    """Eventos só pelo nome (o Phoenix não devolve os atributos de evento)."""
    return [[k, st, msg, attrs, [[e[0], {}] for e in evs]] for k, st, msg, attrs, evs in normalized]


def compare(trace_id: str) -> dict:
    tracing.flush()
    audit = _comparable(parity.normalize_trace(tracing.load(trace_id)))
    phoenix = _comparable(parity.normalize_trace(phoenix_records(trace_id)))
    # o log de auditoria grava status "UNSET" e mensagem None; o Phoenix também — comparação direta
    n, diffs = parity.diff_traces(audit, phoenix)   # a mesma regra da paridade
    return {"ok": bool(audit) and bool(phoenix) and not diffs, "items": n, "audit_spans": len(audit),
            "phoenix_spans": len(phoenix), "diffs": diffs}


if __name__ == "__main__":
    res = compare(sys.argv[1])
    for d in res["diffs"][:15]:
        print(f"≠ {d['key']} · {d['field']}: auditoria={d['default_track']} phoenix={d['stack_track']}")
    print(json.dumps(res, ensure_ascii=False, default=str))
