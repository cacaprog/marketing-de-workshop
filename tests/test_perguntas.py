"""Promessas das perguntas de negócio (005, US5) e do chat (US6): respostas oficiais por regra, vereditos
determinísticos, cada pergunta separa dado bruto de dado com contexto, reapresentação sem rede, chat só leitura."""
import json
import urllib.request

import pytest
from fake_llm import OpenAIStub, tool_call_reply

from agentready import perguntas, toolsets, tracing
from agentready.db import connect, rows
from agentready.llm import parse_brain_spec
from agentready.perguntas import Official, veredito

TOL = 0.02


@pytest.fixture
def results(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTREADY_RESULTS", str(tmp_path))
    return tmp_path


def _official(con):
    return {q.id: o for q, o in perguntas.resolver_todas(con)}


# ---------- resposta oficial (T042)
def test_official_answers_match_the_measured_scenario(con):
    o = _official(con)
    assert o["receita-c01"].valor == pytest.approx(194143.86, rel=0.02)
    assert o["roas-c02"].valor == pytest.approx(2.78, rel=0.02)
    assert o["cac-c06"].valor == pytest.approx(217.55, rel=0.02)
    assert o["investimento-total"].valor == pytest.approx(320820.25, rel=0.02)
    assert o["receita-c03"].status == "desconhecido"
    assert o["roas-c05"].status == "nao_se_aplica"
    assert o["abaixo-do-piso"].campanhas == ["C06"]
    assert o["sem-dados-atuais"].campanhas == ["C03", "C04"]


def test_invalid_question_file_names_the_question(tmp_path):
    bad = tmp_path / "p.yaml"
    bad.write_text("version: 1\ntolerancia_relativa: 0.02\nperguntas:\n  - id: x1\n    texto: t\n"
                   "    resposta_oficial: {tipo: metrica, metrica: lucro_magico, campanha: C01}\n", encoding="utf-8")
    with pytest.raises(perguntas.PerguntaInvalida, match="'x1'.*lucro_magico"):
        perguntas.carregar(bad)


# ---------- regras de veredito (T043)
def test_verdict_rules():
    num = Official("valor", 100.0)
    assert veredito(num, {"status": "valor", "valor": 101.9}, TOL) == "certa"
    assert veredito(num, {"status": "valor", "valor": 103.0}, TOL) == "errada"
    assert veredito(Official("valor", None, ["C06"]), {"status": "valor", "campanhas": ["c06"]}, TOL) == "certa"
    assert veredito(Official("valor", None, ["C06"]), {"status": "valor", "campanhas": ["C05", "C06"]}, TOL) == "errada"
    unk = Official("desconhecido")
    assert veredito(unk, {"status": "valor", "valor": 111815}, TOL) == "inventou_numero"
    assert veredito(unk, {"status": "desconhecido", "valor": None}, TOL) == "desconhecido_correto"
    na = Official("nao_se_aplica")
    assert veredito(na, {"status": "valor", "valor": 0.59}, TOL) == "inventou_numero"   # ROAS da campanha de awareness
    assert veredito(na, {"status": "nao_se_aplica"}, TOL) == "certa"
    assert veredito(num, None, TOL) == "sem_resposta"


# ---------- cada pergunta separa as condições (T044, SC-008)
def _raw_answers(con) -> dict:
    """O que uma consulta correta sobre a Bronze bruta responde (sem quarentena, sem frescor, sem domínio)."""
    def one(sql):
        return con.execute(sql).fetchone()[0]
    win = lambda col, d: f"TRY_CAST({col} AS DATE) >= current_date - {d} AND TRY_CAST({col} AS DATE) < current_date"  # noqa: E731
    gross = lambda cid, d: one(f"SELECT SUM(TRY_CAST(order_value_brl AS DOUBLE)) FROM bronze.conversions "  # noqa: E731
                               f"WHERE campaign_id='{cid}' AND {win('converted_at', d)}")
    spend = lambda cid, d: one(f"SELECT SUM(TRY_CAST(spend_brl AS DOUBLE)) FROM bronze.ad_spend "  # noqa: E731
                               f"WHERE campaign_id='{cid}' AND {win('spend_date', d)}")
    orders = one(f"SELECT COUNT(*) FROM bronze.conversions WHERE campaign_id='C06' AND {win('converted_at', 14)}")
    below = sorted(c for c in ("C01", "C02", "C03", "C04", "C05", "C06") if (gross(c, 14) or 0) / spend(c, 14) < 1.0)
    total = one(f"SELECT SUM(TRY_CAST(spend_brl AS DOUBLE)) FROM bronze.ad_spend WHERE {win('spend_date', 14)}")
    return {"receita-c01": {"status": "valor", "valor": gross("C01", 7)},
            "roas-c02": {"status": "valor", "valor": gross("C02", 14) / spend("C02", 14)},
            "cac-c06": {"status": "valor", "valor": spend("C06", 14) / orders},
            "receita-c03": {"status": "valor", "valor": gross("C03", 7)},
            "roas-c05": {"status": "valor", "valor": gross("C05", 14) / spend("C05", 14)},
            "abaixo-do-piso": {"status": "valor", "campanhas": below},
            "sem-dados-atuais": {"status": "valor", "campanhas": []},
            "investimento-total": {"status": "valor", "valor": total}}


def test_every_question_tells_raw_from_official_except_the_control(con):
    official = _official(con)
    raw = _raw_answers(con)
    for qid, of in official.items():
        right = veredito(of, {"status": of.status, "valor": of.valor, "campanhas": of.campanhas}, TOL)
        assert right in ("certa", "desconhecido_correto"), qid
        wrong = veredito(of, raw[qid], TOL)
        if qid == "investimento-total":
            assert wrong == "certa"                      # controle: dado limpo não precisa de contexto
        else:
            assert wrong in ("errada", "inventou_numero"), (qid, raw[qid], of)


# ---------- ferramentas, arquivo e reapresentação (T045)
def test_question_toolsets_are_read_only(con):
    sem, com = toolsets.leitura_sem(con, responder=True), toolsets.leitura_com(responder=True)
    assert sem.names == ["query_sql", "responder"] and sem.writes == frozenset()
    assert com.names == ["get_data_health", "get_campaign_performance", "read_policy", "responder"]
    assert all(t.reversibility == "R0" for t in sem.tools + com.tools)


def _answer(status, valor=None, campanhas=(), why="x"):
    return tool_call_reply(("responder", {"status": status, "valor": valor, "campanhas": list(campanhas),
                                          "explicacao": why}))


def test_run_saves_file_and_replay_needs_no_network(results, monkeypatch, con):
    before = rows(con, "SELECT * FROM ops.campaigns ORDER BY campaign_id")
    replies = [tool_call_reply(("query_sql", {"sql": "SELECT 1"})), _answer("valor", 244955.22, why="somei a Bronze"),
               tool_call_reply(("get_campaign_performance", {"window_days": 7})), _answer("valor", 194143.86)]
    with OpenAIStub(replies) as stub:
        path = perguntas.rodar(parse_brain_spec(f"local:stub-model@{stub.url}"), ids="receita-c01", pause=False)
    doc = json.loads(path.read_text(encoding="utf-8"))
    assert doc["format"] == "agentready-perguntas/1" and doc["brain"].startswith("local:stub-model@")
    q = doc["questions"][0]
    assert q["respostas"]["sem_contexto"]["veredito"] == "errada"
    assert q["respostas"]["com_contexto"]["veredito"] == "certa"
    assert doc["totals"]["com_contexto"]["certa"] == 1
    assert tracing.load(q["respostas"]["sem_contexto"]["trace_id"])
    c2 = connect()
    try:
        assert rows(c2, "SELECT * FROM ops.change_log") == []
        assert [r["campaign_id"] for r in rows(c2, "SELECT * FROM ops.campaigns ORDER BY campaign_id")] == \
            [r["campaign_id"] for r in before]
    finally:
        c2.close()

    def no_network(*a, **k):
        raise AssertionError("a reapresentação não pode usar a rede")
    monkeypatch.setattr(urllib.request, "urlopen", no_network)
    from rich.console import Console

    from agentready import ui
    monkeypatch.setattr(ui, "console", Console(width=200, highlight=False))
    with ui.console.capture() as cap_:
        perguntas.mostrar(str(path), pause=False)
    out = cap_.get()
    assert "Gravado em" in out and "local:stub-model@" in out and "ERRADA" in out and "CERTA" in out


def test_prose_answer_without_responder_is_sem_resposta(results, con):
    with OpenAIStub([tool_call_reply(content="A receita foi uns 200 mil.")]) as stub:
        _, qs = perguntas.carregar()
        q = next(x for x in qs if x.id == "receita-c01")
        a = perguntas.responder_pergunta(parse_brain_spec(f"local:m@{stub.url}"), "com_contexto", q,
                                         perguntas.resolver(q, con), con, TOL)
    assert a["veredito"] == "sem_resposta" and "200 mil" in a["last_text"]


def test_rules_brain_is_refused_for_questions():
    from agentready.cli import main
    with pytest.raises(SystemExit) as e:
        main(["perguntas", "--brain", "rules", "--sim"])
    assert e.value.code == 1


# ---------- chat (T054)
def test_chat_is_read_only_labelled_and_traced(con, monkeypatch):
    from rich.console import Console

    from agentready import ui
    monkeypatch.setattr(ui, "console", Console(width=200, highlight=False))
    lines = iter(["Qual o ROAS da C02?", "sair"])
    replies = [tool_call_reply(("query_sql", {"sql": "SELECT COUNT(*) FROM bronze.ad_spend"})),
               tool_call_reply(content="Pelos dados brutos, cerca de 3,3.")]
    with OpenAIStub(replies) as stub:
        with ui.console.capture() as cap_:
            perguntas.conversar(parse_brain_spec(f"local:m@{stub.url}"), "sem_contexto", read=lambda _: next(lines))
        offered = [t["function"]["name"] for t in stub.requests[0]["body"]["tools"]]
    out = cap_.get()
    assert offered == ["query_sql"]
    assert "SEM CONTEXTO" in out and "sem contexto>" in out and "3,3" in out
    assert rows(con, "SELECT * FROM ops.change_log") == []


def test_chat_ends_on_eof(con):
    def eof(_):
        raise EOFError
    with OpenAIStub([]) as stub:
        perguntas.conversar(parse_brain_spec(f"local:m@{stub.url}"), "com_contexto", read=eof)
        assert stub.requests == []
