"""Aprovação humana na interface do Airflow (HITL): formulário do pedido e resultado da decisão.

O desfecho é sempre aplicado pelo MESMO caminho da trilha padrão (capabilities.decide_approval),
que reverifica as pré-condições no estado vivo. Sem resposta humana = expirado (falha segura).
"""
from __future__ import annotations

import json
from datetime import datetime

from agentready import capabilities as cap
from agentready.capabilities import brl
from agentready.db import rows

APPROVE, REJECT = "Aprovar", "Rejeitar"
ACTION_LABEL = {"adjust_campaign_budget": "ajustar orçamento diário", "pause_campaign": "pausar campanha"}


def request_details(con, request_id: str, step_result: dict | None = None) -> dict:
    """Tudo que o aprovador precisa ver, montado a partir da fila e do resultado da ação do agente."""
    req = rows(con, "SELECT * FROM ops.approval_queue WHERE request_id=?", [request_id])[0]
    params = json.loads(req["params"])
    cid = params.get("campaign_id")
    camp = rows(con, """SELECT o.daily_budget_brl, o.status, d.campaign_name FROM ops.campaigns o
                        LEFT JOIN gold.dim_campaign d USING (campaign_id) WHERE campaign_id=?""", [cid])
    camp = camp[0] if camp else {}
    res = step_result or {}
    return {
        "request_id": request_id, "action": req["action"], "campaign_id": cid,
        "campaign_name": camp.get("campaign_name") or cid,
        "current": camp.get("daily_budget_brl") if req["action"] == "adjust_campaign_budget" else camp.get("status"),
        "proposed": params.get("new_daily_budget_brl") if req["action"] == "adjust_campaign_budget" else "paused",
        "justification": params.get("justification", ""),
        "checks": res.get("preconditions") or [],
        "autonomy_reasons": (res.get("autonomy") or {}).get("reasons") or [req["reason"]],
        "trace_id": req["trace_id"],
    }


def _fmt(action: str, v) -> str:
    return brl(v) if action == "adjust_campaign_budget" and isinstance(v, (int, float)) else str(v)


def to_hitl_kwargs(d: dict) -> dict:
    """subject/body (Markdown, pt-BR) do formulário HITL — contracts/approval-request.md."""
    action = ACTION_LABEL.get(d["action"], d["action"])
    change = ""
    if d["action"] == "adjust_campaign_budget" and d["current"]:
        change = f" ({(d['proposed'] - d['current']) / d['current']:+.0%})"
    lines = [
        f"**Ação proposta pelo agente:** {action}",
        f"**Campanha:** {d['campaign_id']} · {d['campaign_name']}",
        f"**Atual → proposto:** {_fmt(d['action'], d['current'])} → {_fmt(d['action'], d['proposed'])}{change}",
        f"**Justificativa do agente:** {d['justification']}",
        f"**Por que precisa de você:** {'; '.join(d['autonomy_reasons'])}",
        "",
        "| Pré-condição | Resultado | Detalhe |",
        "|---|---|---|",
        *[f"| {c['id']} | {'✅' if c['passed'] else '❌'} | {c['detail']} |" for c in d["checks"]],
        "",
        f"Trace: `{d['trace_id']}` · Pedido: `{d['request_id']}`",
        "> A aprovação NÃO dispensa as pré-condições: elas serão verificadas de novo no estado vivo.",
    ]
    return {"subject": f"[{d['action']}] {d['campaign_id']} · {d['campaign_name']}", "body": "\n".join(lines)}


def _user_name(user) -> str | None:
    if not user:
        return None
    if isinstance(user, dict):
        return user.get("name") or user.get("id") or None
    return str(user) or None


def outcome(payload: dict | None, timeout_at: datetime | None = None) -> tuple[str, str | None]:
    """Classifica a resposta do HITL: (approve | reject | expired, usuário).

    Sem payload (tarefa HITL falhou/expirou sem defaults), sem usuário que respondeu, ou resposta
    depois do prazo = expirado. O payload do provider não tem um campo explícito de timeout (pesquisa R4).
    """
    if not payload:
        return "expired", None
    user = _user_name(payload.get("responded_by_user"))
    if user is None:
        return "expired", None
    responded = payload.get("responded_at")
    if timeout_at and responded:
        r = datetime.fromisoformat(str(responded)) if not isinstance(responded, datetime) else responded
        if r.replace(tzinfo=None) >= timeout_at.replace(tzinfo=None):
            return "expired", None
    chosen = payload.get("chosen_options") or []
    return ("approve" if chosen == [APPROVE] else "reject"), user


def apply(con, request_id: str, payload: dict | None, timeout_at: datetime | None = None) -> dict:
    """Aplica a decisão humana. Idempotente: pedido que já saiu de 'pending' não muda de novo."""
    pending = rows(con, "SELECT status FROM ops.approval_queue WHERE request_id=?", [request_id])
    if not pending:
        return {"request_id": request_id, "outcome": "unknown_request", "decided_by": None}
    if pending[0]["status"] != "pending":
        return {"request_id": request_id, "outcome": "already_decided", "status": pending[0]["status"],
                "decided_by": None}
    kind, user = outcome(payload, timeout_at)
    comment = ((payload or {}).get("params_input") or {}).get("comentario") or ""
    if comment:
        con.execute("UPDATE ops.approval_queue SET reason = reason || ? WHERE request_id=?",
                    [f" | comentário de {user}: {comment}", request_id])
    if kind == "expired":
        msg = cap.expire_approval(con, request_id, "sem resposta humana dentro do prazo")
        return {"request_id": request_id, "outcome": "expired", "decided_by": "sistema:timeout", "message": msg}
    res = cap.decide_approval(con, request_id, user, approve=(kind == "approve"))
    if isinstance(res, str):  # rejeitado (ou não encontrado)
        return {"request_id": request_id, "outcome": "rejected", "decided_by": user, "message": res}
    if res.status == "executed":
        return {"request_id": request_id, "outcome": "executed", "decided_by": user, "change_id": res.change_id,
                "message": res.message}
    return {"request_id": request_id, "outcome": "rejected_live_recheck", "decided_by": user, "message": res.message}
