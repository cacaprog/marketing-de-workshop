"""Política de guardrails: QUEM decide se uma ação de escrita pode acontecer.

As capacidades (capabilities.py) leem o estado vivo como sempre (campanha, frescor, portfólio, alterações do dia),
juntam os FATOS e perguntam ao avaliador da política. Os limites vêm de config/guardrails.yaml.

- Trilha padrão: `LocalEvaluator` — as mesmas comparações de sempre, em Python, sem rede (Princípio IV).
- Trilha stack (Fase 4): o avaliador é trocado por configuração (`AGENTREADY_POLICY_EVALUATOR=modulo:Classe`) e quem
  decide é o Open Policy Agent. Mesmos ids, mesma ordem, mesmo texto em pt-BR: a frase é montada aqui (`describe`),
  a decisão vem do avaliador. Um teste de equivalência mantém os dois iguais.

Falha fechada: se o avaliador não responder, a ação é negada (`politica_avaliada`). Texto nunca autoriza nada.
"""
from __future__ import annotations

import importlib
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from agentready.settings import ROOT, guardrails

ACOES = ("adjust_campaign_budget", "pause_campaign")
COMMON = ("campanha_existe", "campanha_ativa", "sem_trava_humana", "objetivo_elegivel", "justificativa_presente",
          "dados_frescos")
BUDGET = ("variacao_maxima", "orcamento_minimo", "teto_do_portfolio", "limite_de_alteracoes")
CHECK_IDS = COMMON + BUDGET
FAIL_CLOSED = "politica_avaliada"


@dataclass(frozen=True)
class Fatos:
    """O que as capacidades leram do estado vivo para uma ação (data-model §6)."""
    campaign_id: str
    campanha_existe: bool
    justificativa: str | None = None
    campaign_name: str | None = None
    status: str | None = None
    locked_by_human: bool | None = None
    objective: str | None = None
    conversion_source: str | None = None
    frescor_status: str | None = None          # None = sem linha em gold.source_health ("sem dados")
    frescor_idade_h: float | None = None
    orcamento_atual: float | None = None
    orcamento_novo: float | None = None
    variacao_pct: float | None = None
    soma_outras_ativas: float | None = None
    # A soma é feita UMA vez, aqui (float do Python): a política só compara com o teto. Somar no OPA (decimal
    # exato) poderia discordar do Python bem no limite.
    portfolio_total: float | None = None
    alteracoes_hoje: int | None = None

    def as_input(self) -> dict:
        return {k: (None if isinstance(v, float) and v == float("inf") else v) for k, v in self.__dict__.items()}


@dataclass
class Decisao:
    permitido: bool
    checagens: list[tuple[str, bool]]          # (id, ok) na ordem de hoje
    versao: str
    valores: dict = field(default_factory=dict)


class Evaluator(Protocol):
    nome: str

    def avaliar(self, acao: str, fatos: Fatos, limites: dict) -> Decisao: ...


def policy_version() -> str:
    """A versão da política (stack/policy/VERSION). Sem a pasta da stack: a versão dos limites em uso."""
    f = Path(os.environ.get("AGENTREADY_POLICY_VERSION_FILE", ROOT / "stack" / "policy" / "VERSION"))
    try:
        return f.read_text(encoding="utf-8").strip()
    except OSError:
        return f"local-{guardrails()['version']}"


def _pct(f: Fatos) -> float:
    """Variação do orçamento; orçamento atual zero = infinita (o OPA recebe null: JSON não tem infinito)."""
    return float("inf") if f.variacao_pct is None else f.variacao_pct


def expected_ids(acao: str, fatos: Fatos, limites: dict) -> list[str]:
    """Quais checagens valem para esta ação, na ordem de hoje (o avaliador externo tem de devolver exatamente estas)."""
    if not fatos.campanha_existe:
        return ["campanha_existe"]
    ids = [c for c in COMMON if c != "dados_frescos" or limites["data"]["require_fresh_sources"]]
    return ids + (list(BUDGET) if acao == "adjust_campaign_budget" else [])


class LocalEvaluator:
    """As comparações que moravam em capabilities._common_checks / budget_checks, sem mudança de regra."""
    nome = "local"

    def avaliar(self, acao: str, fatos: Fatos, limites: dict) -> Decisao:
        f, g = fatos, limites
        if not f.campanha_existe:
            return Decisao(False, [("campanha_existe", False)], policy_version())
        ok = {
            "campanha_existe": True,
            "campanha_ativa": f.status == "active",
            "sem_trava_humana": not f.locked_by_human,
            "objetivo_elegivel": f.objective in g["optimization"]["eligible_objectives"],
            "justificativa_presente": bool(f.justificativa and f.justificativa.strip()),
            "dados_frescos": f.frescor_status is not None and f.frescor_status == "fresh",
        }
        if acao == "adjust_campaign_budget":
            b = g["budget"]
            ok |= {
                "variacao_maxima": abs(_pct(f)) <= b["max_change_pct_per_action"],
                "orcamento_minimo": f.orcamento_novo >= b["min_daily_budget_brl"],
                "teto_do_portfolio": f.portfolio_total <= b["portfolio_daily_cap_brl"],
                "limite_de_alteracoes": f.alteracoes_hoje < b["max_changes_per_campaign_per_day"],
            }
        checks = [(i, ok[i]) for i in expected_ids(acao, f, g)]
        return Decisao(all(o for _i, o in checks), checks, policy_version())


def describe(check_id: str, fatos: Fatos, limites: dict) -> str:
    """O detalhe em pt-BR de cada checagem — o mesmo texto que as capacidades sempre gravaram no trace."""
    from agentready.capabilities import brl
    f, g = fatos, limites
    if check_id == "campanha_existe":
        return f"{f.campaign_id} · {f.campaign_name}" if f.campanha_existe else f"{f.campaign_id} não existe na plataforma"
    if check_id == "campanha_ativa":
        return f"status atual: {f.status}"
    if check_id == "sem_trava_humana":
        return "campanha travada manualmente por um humano" if f.locked_by_human else "sem trava"
    if check_id == "objetivo_elegivel":
        return f"objetivo '{f.objective}' (elegíveis: {g['optimization']['eligible_objectives']})"
    if check_id == "justificativa_presente":
        return "justificativa registrada" if f.justificativa else "ação sem justificativa"
    if check_id == "dados_frescos":
        return (f"conversões via {f.conversion_source}: "
                + (f"{f.frescor_status} ({f.frescor_idade_h}h)" if f.frescor_status is not None else "sem dados"))
    b = g["budget"]
    if check_id == "variacao_maxima":
        return (f"{brl(f.orcamento_atual)} -> {brl(f.orcamento_novo)} ({_pct(f):+.0%}); "
                f"limite ±{b['max_change_pct_per_action']:.0%}")
    if check_id == "orcamento_minimo":
        return f"mínimo {brl(b['min_daily_budget_brl'])}"
    if check_id == "teto_do_portfolio":
        return (f"portfólio ficaria em {brl(f.portfolio_total)} "
                f"(teto {brl(b['portfolio_daily_cap_brl'])})")
    if check_id == "limite_de_alteracoes":
        return f"{f.alteracoes_hoje} alteração(ões) hoje; máx {b['max_changes_per_campaign_per_day']}"
    raise ValueError(f"checagem desconhecida: {check_id}")


_cache: dict = {}


def evaluator() -> Evaluator:
    """O avaliador configurado: `AGENTREADY_POLICY_EVALUATOR=modulo:Classe` (stack) ou o local (padrão)."""
    spec = os.environ.get("AGENTREADY_POLICY_EVALUATOR", "").strip()
    if not spec:
        return LocalEvaluator()
    if spec not in _cache:
        mod, _, cls = spec.partition(":")
        _cache[spec] = getattr(importlib.import_module(mod), cls)
    return _cache[spec]()


def evaluate(acao: str, fatos: Fatos) -> tuple[list, str, str]:
    """Checagens prontas para as capacidades: (list[Check], avaliador, versão). Nunca levanta: falha fechada."""
    from agentready.capabilities import Check
    limites = guardrails()
    nome = "?"
    try:
        ev = evaluator()
        nome = ev.nome
        d = ev.avaliar(acao, fatos, limites)
        if [i for i, _ok in d.checagens] != expected_ids(acao, fatos, limites):
            raise ValueError(f"checagens fora do contrato: {[i for i, _ok in d.checagens]}")
        return [Check(i, bool(ok), describe(i, fatos, limites)) for i, ok in d.checagens], nome, d.versao
    except Exception as e:  # noqa: BLE001 — qualquer falha do avaliador = ação negada
        return [Check(FAIL_CLOSED, False, f"não foi possível avaliar a política: {type(e).__name__}: {e}")], nome, "?"
