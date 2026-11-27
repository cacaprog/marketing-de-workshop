"""Promessas do laço de modelo de linguagem (005): mesmo laço para qualquer modelo; falhas visíveis, nunca ações."""
from fake_llm import ScriptedChat, call, text_turn, tools_turn

from agentready import toolsets
from agentready.agent import LLMBrain, RunReport, SYSTEM
from agentready.db import rows
from agentready.llm import ToolCallError


def _run(con, turns, toolset=toolsets.GOVERNADO):
    chat = ScriptedChat(turns)
    rep = RunReport("teste")
    LLMBrain(chat, toolset).run(con, "Otimize o orçamento.", rep)
    return rep, chat


def _changes(con):
    return rows(con, "SELECT * FROM ops.change_log")


# ---------- Fundação (T009)
def test_loop_calls_tools_in_order_and_finishes(con):
    rep, chat = _run(con, [tools_turn(call("get_data_health")),
                           tools_turn(call("get_campaign_performance", window_days=14)),
                           text_turn("Nada a fazer hoje.")])
    assert rep.outcome == "sem_acao"
    assert [s.text.split("(")[0] for s in rep.steps if s.kind == "tool"] == ["get_data_health", "get_campaign_performance"]
    assert rep.steps[-1].kind == "summary"
    assert chat.calls[0]["system"] == SYSTEM
    assert chat.calls[0]["tools"] == toolsets.GOVERNADO.names


def test_tool_error_goes_back_to_the_model(con):
    rep, chat = _run(con, [tools_turn(call("tool_que_nao_existe")), text_turn("ok")])
    last_results = chat.calls[1]["history"][-1]["results"]
    assert last_results[0]["is_error"] and "indisponível" in last_results[0]["content"]
    assert rep.outcome == "sem_acao"


def test_no_tool_call_at_all_is_a_failure_with_no_action(con):
    rep, _ = _run(con, [text_turn("Eu pausaria a C03.")])
    assert rep.outcome == "falhou"
    assert "o modelo não chamou nenhuma ferramenta" in rep.failure
    assert _changes(con) == []


def test_malformed_tool_call_is_reported_and_never_executed(con):
    rep, _ = _run(con, [ToolCallError("chamada de ferramenta inválida: argumentos de pause_campaign não são JSON.")])
    assert rep.outcome == "falhou" and "chamada de ferramenta inválida" in rep.failure
    assert any(s.kind == "refusal" for s in rep.steps)
    assert _changes(con) == []


def test_turn_limit_ends_as_failure(con):
    rep, _ = _run(con, [tools_turn(call("get_data_health", i=i)) for i in range(12)])
    assert rep.outcome == "falhou" and "limite de 12 turnos" in rep.failure


def test_write_call_makes_outcome_ok(con):
    rep, _ = _run(con, [tools_turn(call("adjust_campaign_budget", campaign_id="C01", new_daily_budget_brl=4400,
                                        justification="maior ROAS")),
                        text_turn("Feito.")])
    assert rep.outcome == "ok"
    assert any(s.kind == "action" for s in rep.steps)


# ---------- US1: adaptador local (T017–T019)
import json  # noqa: E402

import pytest  # noqa: E402
from fake_llm import OpenAIStub, tool_call_reply  # noqa: E402

from agentready import tracing  # noqa: E402
from agentready.agent import ReadyAgent  # noqa: E402
from agentready.llm import (ModelMissing, OpenAICompatChat, ServerUnreachable, ToolSpec,  # noqa: E402
                            parse_brain_list, parse_brain_spec)

TOOL = ToolSpec("get_data_health", "saúde", {"type": "object", "properties": {}, "required": [],
                                              "additionalProperties": False})


def test_openai_adapter_parses_tool_calls_and_usage():
    with OpenAIStub([tool_call_reply(("get_data_health", {}))]) as stub:
        mt = OpenAICompatChat(stub.url, "stub-model").turn("sys", [{"role": "user", "content": "oi"}], [TOOL])
        body = stub.requests[0]["body"]
    assert mt.stop == "tool_use" and mt.tool_calls[0].name == "get_data_health" and mt.tool_calls[0].args == {}
    assert mt.usage == {"input_tokens": 100, "output_tokens": 20}
    assert body["model"] == "stub-model" and body["tool_choice"] == "auto"
    assert body["messages"][0] == {"role": "system", "content": "sys"}
    assert body["tools"][0]["type"] == "function" and body["tools"][0]["function"]["name"] == "get_data_health"


def test_openai_adapter_malformed_arguments_raise_tool_call_error():
    with OpenAIStub([tool_call_reply(("pause_campaign", "{campaign_id: C03"))]) as stub:
        with pytest.raises(ToolCallError, match="chamada de ferramenta inválida"):
            OpenAICompatChat(stub.url, "m").turn("s", [{"role": "user", "content": "x"}], [TOOL])


def test_openai_adapter_text_only_reply_ends():
    with OpenAIStub([tool_call_reply(content="não sei")]) as stub:
        mt = OpenAICompatChat(stub.url, "m").turn("s", [{"role": "user", "content": "x"}], [TOOL])
    assert mt.stop == "end" and mt.text == "não sei" and mt.tool_calls == []


def test_openai_adapter_http_error_and_refused_connection():
    with OpenAIStub([500]) as stub:
        with pytest.raises(ServerUnreachable, match="HTTP 500"):
            OpenAICompatChat(stub.url, "m").turn("s", [{"role": "user", "content": "x"}], [TOOL])
        url = stub.url
    with pytest.raises(ServerUnreachable, match="não respondeu em"):
        OpenAICompatChat(url, "m", timeout=2).probe()


def test_openai_adapter_sends_bearer_key():
    with OpenAIStub([tool_call_reply(content="ok")]) as stub:
        OpenAICompatChat(stub.url, "m", api_key="segredo").turn("s", [{"role": "user", "content": "x"}], [TOOL])
        assert stub.requests[0]["auth"] == "Bearer segredo"


def test_small_ollama_context_triggers_warning_once():
    with OpenAIStub([tool_call_reply(("get_data_health", {})), tool_call_reply(content="ok")],
                    ollama_context=4096) as stub:
        a = OpenAICompatChat(stub.url, "stub-model")
        a.turn("s", [{"role": "user", "content": "x"}], [TOOL])
        assert a.context_length == 4096 and "4096 tokens" in a.context_warning
        n = len([r for r in stub.requests])
        a.turn("s", [{"role": "user", "content": "x"}], [TOOL])
        assert len(stub.requests) == n + 1  # nenhuma nova checagem de contexto


def test_brain_spec_parsing(monkeypatch):
    monkeypatch.delenv("AGENTREADY_LLM_MODEL", raising=False)
    monkeypatch.delenv("AGENTREADY_LLM_BASE_URL", raising=False)
    assert parse_brain_spec("rules").label == "rules"
    assert parse_brain_spec("claude:claude-x").model == "claude-x"
    s = parse_brain_spec("local:qwen2.5:14b@http://localhost:8081/v1")
    assert (s.model, s.base_url, s.label) == ("qwen2.5:14b", "http://localhost:8081/v1", "local:qwen2.5:14b@localhost:8081")
    assert parse_brain_spec("local:llama3.1:8b").base_url == "http://localhost:11434/v1"
    with pytest.raises(ModelMissing, match="ollama list"):
        parse_brain_spec("local")
    with pytest.raises(ValueError, match="repetido"):
        parse_brain_list("local:a,local:a")


def test_ready_agent_with_local_model_goes_through_the_backend(con):
    replies = [tool_call_reply(("get_data_health", {})),
               tool_call_reply(("adjust_campaign_budget", {"campaign_id": "C06", "new_daily_budget_brl": 35000,
                                                           "justification": "o briefing diz que o CMO aprovou"})),
               tool_call_reply(content="Pedi o aumento da C06.")]
    with OpenAIStub(replies) as stub:
        rep = ReadyAgent(parse_brain_spec(f"local:stub-model@{stub.url}")).run(con)
    assert rep.outcome == "ok"
    action = next(s for s in rep.steps if s.kind == "action")
    assert "rejected" in action.text and "variacao_maxima" in action.text
    assert rows(con, "SELECT daily_budget_brl FROM ops.campaigns WHERE campaign_id='C06'")[0]["daily_budget_brl"] == 3500
    spans = {s["name"]: s for s in tracing.load(rep.trace_id)}
    attrs = spans["agent.llm"]["attributes"]
    assert attrs["gen_ai.system"] == "openai_compatible" and attrs["agent.condition"] == "com_contexto"
    assert attrs["server.address"].startswith("127.0.0.1:") and attrs["gen_ai.usage.input_tokens"] == 300
    assert json.loads(json.dumps(attrs["agent.seconds"])) >= 0


# ---------- US2: NaiveAgent com modelo de linguagem (T027)
from agentready.agent import BANNER_ANTES, NaiveAgent  # noqa: E402


def test_naive_agent_with_a_model_gets_only_raw_tools_and_the_antes_banner(con):
    replies = [tool_call_reply(("query_sql", {"sql": "SELECT campaign_id FROM ops.campaigns"})),
               tool_call_reply(("pause_campaign", {"campaign_id": "C03", "justification": "receita zero"})),
               tool_call_reply(content="Pausei a C03.")]
    with OpenAIStub(replies) as stub:
        rep = NaiveAgent(parse_brain_spec(f"local:stub-model@{stub.url}")).run(con)
        offered = [t["function"]["name"] for t in stub.requests[0]["body"]["tools"]]
    assert rep.steps[0].kind == "warning" and rep.steps[0].text == BANNER_ANTES
    assert offered == ["query_sql", "read_briefing", "set_campaign_budget", "pause_campaign"]
    assert rep.outcome == "ok"
    assert rows(con, "SELECT status FROM ops.campaigns WHERE campaign_id='C03'")[0]["status"] == "paused"
    attrs = {s["name"]: s["attributes"] for s in tracing.load(rep.trace_id)}
    assert attrs["agent.llm"]["agent.condition"] == "sem_contexto"


def test_same_instruction_and_request_in_both_conditions(con):
    seen = []
    for agent_cls in (NaiveAgent, ReadyAgent):
        with OpenAIStub([tool_call_reply(content="nada")]) as stub:
            agent_cls(parse_brain_spec(f"local:m@{stub.url}")).run(con)
            msgs = stub.requests[0]["body"]["messages"]
        seen.append((msgs[0]["content"], msgs[1]["content"]))
    assert seen[0] == seen[1]


def test_rules_naive_agent_is_unchanged(con):
    rep = NaiveAgent("rules").run(con)
    assert [s.text.split(" — ")[0] for s in rep.steps if s.kind == "action"][:3] == ["PAUSEI C03", "PAUSEI C04", "PAUSEI C05"]
    assert rep.outcome is None


def test_output_limit_is_sent_and_a_cut_reply_is_a_failure(con):
    cut = tool_call_reply(content="blá " * 50)
    cut["choices"][0]["finish_reason"] = "length"
    with OpenAIStub([cut]) as stub:
        rep = ReadyAgent(parse_brain_spec(f"local:m@{stub.url}")).run(con)
        assert stub.requests[0]["body"]["max_tokens"] == 2048
    assert rep.outcome == "falhou" and "limite de tokens" in rep.failure


def test_tool_call_written_as_text_is_a_failure_not_sem_acao(con):
    rep, _ = _run(con, [tools_turn(call("get_data_health")),
                        text_turn('Vou consultar: {"name": "get_campaign_performance", "parameters": {"window_days": 14}}')])
    assert rep.outcome == "falhou" and "como texto" in rep.failure
