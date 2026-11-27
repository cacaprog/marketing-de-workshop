"""Modelos de mentira para testes offline: nenhum teste chama um modelo de verdade (FR-024).

* ScriptedChat — adaptador que devolve turnos pré-definidos (inclusive falhas).
* OpenAIStub   — servidor HTTP local (biblioteca padrão) que fala o protocolo de chat-completions,
                 para exercitar o adaptador real OpenAICompatChat.
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from agentready.llm import LLMError, ModelTurn, ToolCall


class ScriptedChat:
    system_name = "scripted"
    server_address = "teste"

    def __init__(self, turns, model: str = "roteiro"):
        """`turns`: lista de ModelTurn, de LLMError (levantado) ou de callables(history) -> ModelTurn."""
        self.turns = list(turns)
        self.model = model
        self.calls: list[dict] = []
        self.context_warning = None
        self.context_length = None

    def turn(self, system, history, tools):
        self.calls.append({"system": system, "history": list(history), "tools": [t.name for t in tools]})
        if not self.turns:
            return ModelTurn("fim do roteiro", [], "end")
        nxt = self.turns.pop(0)
        if isinstance(nxt, LLMError):
            raise nxt
        if callable(nxt):
            return nxt(history)
        return nxt

    def probe(self):
        return None


def call(name: str, i: int = 0, **args) -> ToolCall:
    return ToolCall(f"c{i}-{name}", name, args)


def tools_turn(*calls: ToolCall, text: str = "") -> ModelTurn:
    return ModelTurn(text, list(calls), "tool_use", {"input_tokens": 10, "output_tokens": 5})


def text_turn(text: str) -> ModelTurn:
    return ModelTurn(text, [], "end", {"input_tokens": 10, "output_tokens": 5})


def tool_call_reply(*calls: tuple[str, object], content: str = "") -> dict:
    """Resposta no formato chat-completions. `args` pode ser dict ou string crua (para JSON quebrado)."""
    tcs = [{"id": f"call_{i}", "type": "function",
            "function": {"name": n, "arguments": a if isinstance(a, str) else json.dumps(a)}}
           for i, (n, a) in enumerate(calls)]
    msg = {"role": "assistant", "content": content}
    if tcs:
        msg["tool_calls"] = tcs
    return {"choices": [{"index": 0, "message": msg, "finish_reason": "tool_calls" if tcs else "stop"}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}}


class OpenAIStub:
    """Servidor local que responde /v1/models e /v1/chat/completions a partir de uma fila de respostas.

    Cada item da fila é um dict (resposta JSON 200) ou um int (código HTTP de erro).
    Opcionalmente imita o Ollama (/api/version e /api/ps com `context_length`)."""

    def __init__(self, replies=None, ollama_context: int | None = None):
        self.replies = list(replies or [])
        self.requests: list[dict] = []
        self.ollama_context = ollama_context
        stub = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code, obj):
                body = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                if self.path.endswith("/v1/models"):
                    return self._send(200, {"data": [{"id": "stub"}]})
                if stub.ollama_context and self.path == "/api/version":
                    return self._send(200, {"version": "0.0-stub"})
                if stub.ollama_context and self.path == "/api/ps":
                    return self._send(200, {"models": [{"name": "stub-model", "model": "stub-model",
                                                        "context_length": stub.ollama_context}]})
                self._send(404, {"error": "not found"})

            def do_POST(self):
                n = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(n) or b"{}")
                stub.requests.append({"path": self.path, "body": body,
                                      "auth": self.headers.get("Authorization")})
                nxt = stub.replies.pop(0) if stub.replies else tool_call_reply(content="fim")
                if isinstance(nxt, int):
                    return self._send(nxt, {"error": "falha simulada"})
                self._send(200, nxt)

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_address[1]}/v1"

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()
