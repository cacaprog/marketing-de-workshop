"""Fase 2 — linhagem: verificação do Marquez (FR-013) e o endereço da tarefa do agente na UI.

A emissão dos eventos é do provider OpenLineage do Airflow e do Cosmos (nada a emitir daqui). Se o
Marquez cair, nada falha: a execução segue e o fechamento registra um aviso visível.
"""
from __future__ import annotations

import json
import os
import urllib.request

NAMESPACE = "aurora"
AGENT_JOB = "aurora_midia_diario.agente.executar"


def marquez_url() -> str:
    return os.environ.get("MARQUEZ_URL", "http://marquez-api:5000")


def agent_job_link() -> str:
    port = os.environ.get("MARQUEZ_WEB_PORT", "3000")
    return f"http://localhost:{port}/lineage/job/{NAMESPACE}/{AGENT_JOB}"


def check(timeout: float = 5) -> dict:
    """Nunca levanta exceção. ok=False com o motivo quando o Marquez não responde."""
    try:
        with urllib.request.urlopen(f"{marquez_url()}/api/v1/namespaces/{NAMESPACE}", timeout=timeout) as r:
            json.load(r)
        return {"ok": True, "url": marquez_url()}
    except Exception as e:  # noqa: BLE001 - qualquer falha vira aviso, nunca falha da execução
        reason = getattr(e, "reason", None) or str(e) or type(e).__name__
        if getattr(e, "code", None) == 404:
            reason = "namespace 'aurora' ainda sem eventos"
        return {"ok": False, "url": marquez_url(), "reason": str(reason)}
