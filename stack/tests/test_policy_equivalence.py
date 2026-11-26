"""Fase 4 (FR-015a, SC-006/006a) — a política em Python (trilha padrão) e no OPA (stack) decidem igual, caso a caso.

Precisa do serviço `opa` no ar (como o Postgres para os outros testes): `make up` antes de `make test`.
A mutação dos limites NUNCA escreve no OPA: cada consulta usa `with data.guardrails as <limites alterados>`.
"""
import copy
import json
import os
import urllib.request
from pathlib import Path

import pytest
import yaml

from agentready import policy
from agentready.settings import guardrails
from agentready_stack import policy_opa

CASOS = Path(__file__).resolve().parents[1] / "policy" / "testes" / "casos.yaml"
OPA = os.environ.get("OPA_URL", "http://opa:8181").rstrip("/")


def _opa_up() -> bool:
    try:
        urllib.request.urlopen(OPA + "/health", timeout=2).read()
        return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(not _opa_up(), reason="OPA fora do ar: rode `make up` antes de `make test`")


def _casos():
    return yaml.safe_load(CASOS.read_text(encoding="utf-8"))


def _local(acao, fatos, limites):
    return [(i, ok) for i, ok in policy.LocalEvaluator().avaliar(acao, fatos, limites).checagens]


def _opa(acao, fatos, limites=None):
    """Consulta ad hoc (só leitura); com `limites`, troca data.guardrails SÓ nesta consulta."""
    q = "x := data.agentready.guardrails.decisao with input as " + json.dumps({"acao": acao, "fatos": fatos.as_input()})
    if limites is not None:
        q += " with data.guardrails as " + json.dumps(limites)
    req = urllib.request.Request(OPA + "/v1/query", data=json.dumps({"query": q}).encode(),
                                 headers={"Content-Type": "application/json"})
    res = json.load(urllib.request.urlopen(req, timeout=5))["result"][0]["x"]
    return [(c["id"], c["ok"]) for c in res["checagens"]]


def test_every_case_same_checks_order_verdicts_and_text(monkeypatch):
    lim = guardrails()
    for caso in _casos():
        f = policy.Fatos(**caso["fatos"])
        local, opa = _local(caso["acao"], f, lim), _opa(caso["acao"], f)
        assert local == opa, caso["nome"]
        assert sorted(i for i, ok in local if not ok) == sorted(caso["esperado_falhas"]), caso["nome"]
        monkeypatch.delenv("AGENTREADY_POLICY_EVALUATOR", raising=False)
        a = [(c.id, c.passed, c.detail) for c in policy.evaluate(caso["acao"], f)[0]]
        monkeypatch.setenv("AGENTREADY_POLICY_EVALUATOR", "agentready_stack.policy_opa:OpaEvaluator")
        b = [(c.id, c.passed, c.detail) for c in policy.evaluate(caso["acao"], f)[0]]
        assert a == b, f"{caso['nome']}: o texto em pt-BR é o mesmo nas duas trilhas"


def test_each_guardrail_has_a_passing_and_a_failing_case():
    passing, failing = set(), set()
    for caso in _casos():
        for i, ok in _local(caso["acao"], policy.Fatos(**caso["fatos"]), guardrails()):
            (passing if ok else failing).add(i)
    assert passing == failing == set(policy.CHECK_IDS)


def test_policy_version_matches_the_version_file():
    assert policy_opa.preflight() == (Path(__file__).resolve().parents[1] / "policy" / "VERSION").read_text().strip()
    assert policy.policy_version() == policy_opa.preflight()


MUTATIONS = [("budget", "max_change_pct_per_action", 0.35), ("budget", "max_change_pct_per_action", 0.05),
             ("budget", "min_daily_budget_brl", 100), ("budget", "min_daily_budget_brl", 5000),
             ("budget", "portfolio_daily_cap_brl", 40000), ("budget", "portfolio_daily_cap_brl", 20000),
             ("budget", "max_changes_per_campaign_per_day", 1), ("budget", "max_changes_per_campaign_per_day", 5),
             ("optimization", "eligible_objectives", ["conversion", "awareness"]),
             ("data", "require_fresh_sources", False)]


@pytest.mark.parametrize("section,key,value", MUTATIONS, ids=lambda v: str(v))
def test_changing_any_limit_changes_some_verdict_in_both_evaluators(section, key, value):
    orig = guardrails()
    mut = copy.deepcopy(orig)
    mut[section][key] = value
    changed = False
    for caso in _casos():
        f = policy.Fatos(**caso["fatos"])
        before, after_local, after_opa = _local(caso["acao"], f, orig), _local(caso["acao"], f, mut), _opa(caso["acao"], f, mut)
        assert after_local == after_opa, (caso["nome"], key, value)
        changed |= before != after_local
    assert changed, f"mudar {section}.{key} para {value} não mudou nenhum veredito: falta caso de teste"
