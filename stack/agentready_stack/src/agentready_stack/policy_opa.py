"""Fase 4 — o avaliador da política na trilha stack: o Open Policy Agent decide (Bloco 3).

Ligado por configuração (`AGENTREADY_POLICY_EVALUATOR=agentready_stack.policy_opa:OpaEvaluator`): as capacidades
compartilhadas montam os fatos e perguntam; este módulo só faz a pergunta ao OPA e confere a resposta. Qualquer
problema (OPA fora do ar, lento, resposta estranha) levanta exceção, e `agentready.policy.evaluate` nega a ação
(falha fechada). A frase em pt-BR é montada pelo código compartilhado, igual nas duas trilhas.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from agentready.policy import CHECK_IDS, Decisao, Fatos

TIMEOUT_S = 2.0
PATH = "/v1/data/agentready/guardrails/decisao"


class PolicyUnavailable(RuntimeError):
    """A política não pôde ser avaliada (mensagem em pt-BR)."""


def opa_url() -> str:
    return os.environ.get("OPA_URL", "http://opa:8181").rstrip("/")


def _post(body: dict, timeout: float = TIMEOUT_S) -> dict:
    req = urllib.request.Request(opa_url() + PATH, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            if r.status != 200:
                raise PolicyUnavailable(f"OPA respondeu {r.status}")
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise PolicyUnavailable(f"OPA respondeu {e.code}") from e
    except (OSError, ValueError) as e:
        raise PolicyUnavailable(f"OPA inacessível em {opa_url()} ({type(e).__name__})") from e


def _validate(result) -> Decisao:
    if not isinstance(result, dict) or not {"permitido", "checagens", "versao"} <= set(result):
        raise PolicyUnavailable("resposta do OPA fora do contrato (sem permitido/checagens/versao): a política "
                                "não está carregada?")
    checks = []
    for c in result["checagens"]:
        if not isinstance(c, dict) or c.get("id") not in CHECK_IDS or not isinstance(c.get("ok"), bool):
            raise PolicyUnavailable(f"checagem fora do contrato na resposta do OPA: {c}")
        checks.append((c["id"], c["ok"]))
    if not isinstance(result["permitido"], bool) or result["permitido"] != all(ok for _i, ok in checks):
        raise PolicyUnavailable("o OPA respondeu `permitido` incoerente com as checagens")
    return Decisao(result["permitido"], checks, str(result["versao"]), result.get("valores") or {})


class OpaEvaluator:
    nome = "opa"

    def avaliar(self, acao: str, fatos: Fatos, limites: dict) -> Decisao:
        # `limites` não vai junto: o OPA lê o MESMO config/guardrails.yaml como data.guardrails.
        resp = _post({"input": {"acao": acao, "fatos": fatos.as_input()}})
        if "result" not in resp:
            raise PolicyUnavailable("o OPA não tem a decisão agentready.guardrails.decisao (política não carregada)")
        return _validate(resp["result"])


PROBE = Fatos(campaign_id="SONDA", campanha_existe=True, justificativa="sonda do preflight", campaign_name="sonda",
              status="active", locked_by_human=False, objective="conversion", conversion_source="ga4",
              frescor_status="fresh", frescor_idade_h=1.0, orcamento_atual=1000.0, orcamento_novo=1000.0,
              variacao_pct=0.0, soma_outras_ativas=0.0, portfolio_total=1000.0, alteracoes_hoje=0)


def preflight() -> str:
    """Antes do agente rodar: o OPA está no ar e a política responde dentro do contrato? Devolve a versão.
    Senão, levanta PolicyUnavailable — a tarefa do agente falha e nada é executado (falha fechada)."""
    try:
        with urllib.request.urlopen(opa_url() + "/health?bundles", timeout=TIMEOUT_S) as r:
            if r.status != 200:
                raise PolicyUnavailable(f"/health do OPA respondeu {r.status}")
    except urllib.error.HTTPError as e:
        raise PolicyUnavailable(f"/health do OPA respondeu {e.code}") from e
    except OSError as e:
        raise PolicyUnavailable(f"OPA inacessível em {opa_url()} ({type(e).__name__})") from e
    return OpaEvaluator().avaliar("adjust_campaign_budget", PROBE, {}).versao
