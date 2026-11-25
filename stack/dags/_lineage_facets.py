"""Fase 2 — linhagem: o trace_id da execução do agente vira um "run facet" do OpenLineage (FR-010).

É isso que liga a linhagem (Marquez) ao livro de alterações (ops.change_log.trace_id): da tarefa
agente.executar no Marquez chega-se às decisões que ela tomou. O provider OpenLineage chama esta função
pelo [openlineage] custom_run_facets (veja compose.yaml). Fica na pasta de DAGs porque o ambiente do
orquestrador não importa o pacote agentready_stack (ele vive no venv do agente).
"""
from __future__ import annotations

import attr
from openlineage.client.facet_v2 import RunFacet

AGENT_TASK = "agente.executar"


@attr.define
class AgentreadyTraceRunFacet(RunFacet):
    """trace_id do agentready (o mesmo de ops.change_log e ops.approval_queue) e o que o agente fez:
    'done' (decidiu) ou 'skipped_duplicate' (mesmos dados de antes: o agente não rodou, não há trace)."""
    status: str
    trace_id: str | None = None

    @staticmethod
    def _get_schema() -> str:
        return "urn:agentready:facet:trace:1.1.0"


def trace_facet(task_instance, ti_state) -> dict:
    if getattr(task_instance, "task_id", None) != AGENT_TASK:
        return {}
    try:
        result = task_instance.xcom_pull(task_ids=AGENT_TASK) or {}
    except Exception:  # noqa: BLE001 - no START ainda não há XCom; linhagem nunca derruba a tarefa
        return {}
    if not isinstance(result, dict) or not result.get("status"):
        return {}
    return {"agentready_trace": AgentreadyTraceRunFacet(status=result["status"], trace_id=result.get("trace_id"))}
