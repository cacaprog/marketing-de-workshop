"""Política de guardrails (agentready.policy): o avaliador local decide igual ao que as capacidades sempre fizeram,
o avaliador é trocável por configuração e qualquer falha dele nega a ação (falha fechada)."""
import pytest

from agentready import capabilities, policy
from agentready.settings import guardrails

BASE = dict(campaign_id="C01", campanha_existe=True, justificativa="ROAS 7,5", campaign_name="Google Search - Marca",
            status="active", locked_by_human=False, objective="conversion", conversion_source="ga4",
            frescor_status="fresh", frescor_idade_h=3.0, orcamento_atual=4000.0, orcamento_novo=4400.0,
            variacao_pct=0.1, soma_outras_ativas=20000.0, portfolio_total=24400.0, alteracoes_hoje=0)


def _f(**kw):
    return policy.Fatos(**(BASE | kw))


def _ids(checks):
    return [(c.id, c.passed) for c in checks]


def test_local_evaluator_keeps_the_exact_details(monkeypatch):
    monkeypatch.delenv("AGENTREADY_POLICY_EVALUATOR", raising=False)
    checks, nome, _v = policy.evaluate("adjust_campaign_budget", _f(orcamento_novo=5200.0, variacao_pct=0.3,
                                                                       portfolio_total=25200.0))
    assert nome == "local"
    d = {c.id: c.detail for c in checks}
    assert d["variacao_maxima"] == "R$ 4.000 -> R$ 5.200 (+30%); limite ±20%"
    assert d["teto_do_portfolio"] == "portfólio ficaria em R$ 25.200 (teto R$ 26.000)"
    assert d["orcamento_minimo"] == "mínimo R$ 300"
    assert d["limite_de_alteracoes"] == "0 alteração(ões) hoje; máx 2"
    assert d["objetivo_elegivel"] == "objetivo 'conversion' (elegíveis: ['conversion'])"
    assert d["dados_frescos"] == "conversões via ga4: fresh (3.0h)"
    assert d["campanha_existe"] == "C01 · Google Search - Marca"
    assert [i for i, _ in _ids(checks)] == list(policy.CHECK_IDS)
    assert [c.id for c in checks if not c.passed] == ["variacao_maxima"]


def test_missing_campaign_returns_only_that_check():
    checks, _n, _v = policy.evaluate("adjust_campaign_budget",
                                     policy.Fatos(campaign_id="C99", campanha_existe=False, justificativa="x"))
    assert _ids(checks) == [("campanha_existe", False)] and checks[0].detail == "C99 não existe na plataforma"


def test_fresh_data_check_follows_the_guardrail_flag(monkeypatch):
    g = guardrails() | {"data": {"require_fresh_sources": False}}
    monkeypatch.setattr(policy, "guardrails", lambda: g)
    checks, _n, _v = policy.evaluate("pause_campaign", _f(frescor_status=None))
    assert "dados_frescos" not in [c.id for c in checks]


def test_pause_has_no_budget_checks_and_whitespace_justification_fails():
    checks, _n, _v = policy.evaluate("pause_campaign", _f(justificativa="   "))
    assert [c.id for c in checks] == list(policy.COMMON)
    assert [c.id for c in checks if not c.passed] == ["justificativa_presente"]


class _Boom:
    nome = "quebrado"

    def avaliar(self, acao, fatos, limites):
        raise ConnectionError("sem rede")


class _WrongOrder:
    nome = "fora_de_ordem"

    def avaliar(self, acao, fatos, limites):
        d = policy.LocalEvaluator().avaliar(acao, fatos, limites)
        return policy.Decisao(d.permitido, list(reversed(d.checagens)), d.versao)


def test_evaluator_is_loaded_from_configuration_and_fails_closed(monkeypatch):
    monkeypatch.setenv("AGENTREADY_POLICY_EVALUATOR", "tests.test_policy:_Boom")
    import sys
    sys.modules.setdefault("tests.test_policy", sys.modules[__name__])
    checks, nome, _v = policy.evaluate("adjust_campaign_budget", _f())
    assert nome == "quebrado"
    assert [(c.id, c.passed) for c in checks] == [("politica_avaliada", False)]
    assert checks[0].detail.startswith("não foi possível avaliar a política:")
    monkeypatch.setenv("AGENTREADY_POLICY_EVALUATOR", "tests.test_policy:_WrongOrder")
    checks, _n, _v = policy.evaluate("adjust_campaign_budget", _f())
    assert [c.id for c in checks] == ["politica_avaliada"], "resposta fora do contrato também nega"


def test_action_span_records_who_decided(tmp_path, monkeypatch):
    """A ação registra no trace o avaliador e a versão da política (Fase 4)."""
    monkeypatch.delenv("AGENTREADY_POLICY_EVALUATOR", raising=False)
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
    exp = InMemorySpanExporter()
    prov = TracerProvider()
    prov.add_span_processor(SimpleSpanProcessor(exp))
    with prov.get_tracer("t").start_as_current_span("tool.adjust_campaign_budget"):
        capabilities._policy_checks("adjust_campaign_budget", _f())
    attrs = exp.get_finished_spans()[0].attributes
    assert attrs["policy.evaluator"] == "local" and attrs["policy.version"] == policy.policy_version()
