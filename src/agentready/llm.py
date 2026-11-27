"""Modelos de linguagem como "cérebro" do agente: tipos neutros e adaptadores por provedor.

O laço do agente (agent.LLMBrain) só conhece estes tipos. Cada adaptador traduz:
  * AnthropicChat     -> API da Anthropic (Claude), com as mesmas opções de sempre;
  * OpenAICompatChat  -> qualquer servidor no protocolo de chat-completions com ferramentas
                         (Ollama, llama.cpp `llama serve`/`llama-server`), só com a biblioteca padrão.

O modelo do Claude é configurado num único lugar: DEFAULT_CLAUDE_MODEL / AGENTREADY_MODEL.
"""
from __future__ import annotations

import json
import os
import socket
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from urllib.parse import urlparse

DEFAULT_CLAUDE_MODEL = "claude-opus-5-5"
DEFAULT_LOCAL_URL = "http://localhost:11434/v1"
MIN_CONTEXT = 16384


# ------------------------------------------------------------------ tipos neutros

@dataclass
class ToolSpec:
    name: str
    description: str
    schema: dict
    reversibility: str = "R0"


@dataclass
class ToolCall:
    id: str
    name: str
    args: dict


@dataclass
class ModelTurn:
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    stop: str = "end"                 # tool_use | end | refusal | length
    usage: dict | None = None         # {"input_tokens": int, "output_tokens": int}
    seconds: float = 0.0
    raw: object = None                # resposta nativa do provedor (para devolver no histórico)


class LLMError(Exception):
    """Falha que encerra a execução do modelo (mensagem já em pt-BR)."""


class ToolCallError(LLMError):
    pass


class ServerUnreachable(LLMError):
    pass


class ModelMissing(LLMError):
    pass


# ------------------------------------------------------------------ especificação do cérebro

@dataclass
class BrainSpec:
    kind: str                         # rules | claude | local
    model: str | None = None
    base_url: str | None = None

    @property
    def label(self) -> str:
        if self.kind == "rules":
            return "rules"
        if self.kind == "claude":
            return f"claude:{self.model}"
        return f"local:{self.model}@{_host_port(self.base_url)}"


def _host_port(url: str | None) -> str:
    u = urlparse(url or "")
    return f"{u.hostname}:{u.port}" if u.port else (u.hostname or str(url))


def parse_brain_spec(text: str, default_url: str | None = None, default_model: str | None = None) -> BrainSpec:
    """`rules` · `claude` · `claude:<modelo>` · `local` · `local:<modelo>` · `local:<modelo>@<url>`."""
    text = (text or "").strip()
    if text == "rules":
        return BrainSpec("rules")
    if text == "claude" or text.startswith("claude:"):
        model = text.split(":", 1)[1] if ":" in text else None
        return BrainSpec("claude", model or os.environ.get("AGENTREADY_MODEL") or DEFAULT_CLAUDE_MODEL)
    if text == "local" or text.startswith("local:"):
        rest = text.split(":", 1)[1] if ":" in text else ""
        url = None
        if "@" in rest:
            rest, url = rest.rsplit("@", 1)
        model = rest or default_model or os.environ.get("AGENTREADY_LLM_MODEL")
        url = url or default_url or os.environ.get("AGENTREADY_LLM_BASE_URL") or DEFAULT_LOCAL_URL
        if not model:
            raise ModelMissing("nenhum modelo local informado: use --llm-model <nome> (veja `ollama list`) "
                               "ou defina AGENTREADY_LLM_MODEL.")
        return BrainSpec("local", model, url.rstrip("/"))
    raise ValueError(f"cérebro desconhecido: {text!r}. Use rules, claude, claude:<modelo>, local:<modelo> "
                     "ou local:<modelo>@<url>.")


def parse_brain_list(text: str, default_url: str | None = None) -> list[BrainSpec]:
    specs = [parse_brain_spec(t, default_url) for t in text.split(",") if t.strip()]
    labels = [s.label for s in specs]
    dup = {x for x in labels if labels.count(x) > 1}
    if dup:
        raise ValueError(f"cérebro repetido na lista: {', '.join(sorted(dup))}")
    return specs


def adapter_for(spec: BrainSpec):
    if spec.kind == "claude":
        return AnthropicChat(spec.model)
    if spec.kind == "local":
        return OpenAICompatChat(spec.base_url, spec.model, api_key=os.environ.get("AGENTREADY_LLM_API_KEY"),
                                timeout=float(os.environ.get("AGENTREADY_LLM_TIMEOUT", "300")),
                                max_tokens=int(os.environ.get("AGENTREADY_LLM_MAX_TOKENS", "2048")))
    raise ValueError("o cérebro rules não usa modelo de linguagem")


# ------------------------------------------------------------------ Anthropic (Claude)

class AnthropicChat:
    system_name = "anthropic"
    server_address = "api.anthropic.com"

    def __init__(self, model: str | None = None):
        self.model = model or os.environ.get("AGENTREADY_MODEL") or DEFAULT_CLAUDE_MODEL
        self.context_warning = None
        self.context_length = None

    def probe(self) -> None:
        try:
            import anthropic  # noqa: F401
        except ImportError as e:
            raise ServerUnreachable("o cérebro Claude precisa do extra llm: `uv sync --extra llm`.") from e
        if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
            raise ServerUnreachable("defina ANTHROPIC_API_KEY para usar o cérebro Claude.")

    @staticmethod
    def _tools(tools: list[ToolSpec]) -> list[dict]:
        return [{"name": t.name, "description": t.description, "input_schema": t.schema, "strict": True}
                for t in tools]

    @staticmethod
    def _messages(history: list[dict]) -> list[dict]:
        out = []
        for m in history:
            if m["role"] == "user":
                out.append({"role": "user", "content": m["content"]})
            elif m["role"] == "assistant":
                out.append({"role": "assistant", "content": m["raw"]})
            else:  # tool_results
                out.append({"role": "user", "content": [
                    {"type": "tool_result", "tool_use_id": r["id"], "content": r["content"], "is_error": r["is_error"]}
                    for r in m["results"]]})
        return out

    def turn(self, system: str, history: list[dict], tools: list[ToolSpec]) -> ModelTurn:
        import anthropic

        client = anthropic.Anthropic()
        t0 = time.monotonic()
        resp = client.beta.messages.create(
            model=self.model, max_tokens=16000, system=system, tools=self._tools(tools),
            messages=self._messages(history),
            thinking={"type": "adaptive"}, output_config={"effort": "medium"},
            betas=["server-side-fallback-2026-07-01"], fallbacks="default")
        text = "\n".join(b.text for b in resp.content if b.type == "text" and b.text.strip()).strip()
        calls = [ToolCall(b.id, b.name, dict(b.input)) for b in resp.content if b.type == "tool_use"]
        stop = {"tool_use": "tool_use", "refusal": "refusal", "max_tokens": "length"}.get(resp.stop_reason, "end")
        return ModelTurn(text, calls, stop, {"input_tokens": resp.usage.input_tokens,
                                             "output_tokens": resp.usage.output_tokens},
                         time.monotonic() - t0, raw=resp.content)


# ------------------------------------------------------------------ servidores locais (Ollama, llama.cpp)

class OpenAICompatChat:
    system_name = "openai_compatible"

    def __init__(self, base_url: str, model: str, api_key: str | None = None, timeout: float = 300.0,
                 max_tokens: int = 2048):
        self.base_url = base_url.rstrip("/")
        self.max_tokens = max_tokens  # sem limite, o llama.cpp pode gerar sem parar (medido: 4 098 tokens)
        self.model = model
        self.api_key = api_key
        self.timeout = timeout
        self.server_address = _host_port(self.base_url)
        self.context_length: int | None = None
        self.context_warning: str | None = None
        self._context_checked = False

    # -- HTTP
    def _request(self, url: str, body: dict | None = None, timeout: float | None = None) -> dict:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, headers=headers, method="POST" if data else "GET")
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.timeout) as r:
                return json.loads(r.read().decode("utf-8") or "{}")
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:200]
            raise ServerUnreachable(f"o servidor de modelo em {self.base_url} respondeu HTTP {e.code}: {detail}") from e
        except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError) as e:
            reason = getattr(e, "reason", e)
            raise ServerUnreachable(
                f"o servidor de modelo não respondeu em {self.base_url} ({reason}). Inicie o Ollama (`ollama serve`) "
                f"ou o llama.cpp (`llama serve -m <modelo.gguf> --jinja --port 8081`).") from e
        except json.JSONDecodeError as e:
            raise ServerUnreachable(f"o servidor de modelo em {self.base_url} devolveu uma resposta que não é JSON.") from e

    def probe(self) -> None:
        self._request(f"{self.base_url}/models", timeout=5)

    # -- conversão de formato
    @staticmethod
    def _tools(tools: list[ToolSpec]) -> list[dict]:
        return [{"type": "function", "function": {"name": t.name, "description": t.description,
                                                  "parameters": t.schema}} for t in tools]

    @staticmethod
    def _messages(system: str, history: list[dict]) -> list[dict]:
        out = [{"role": "system", "content": system}]
        for m in history:
            if m["role"] == "user":
                out.append({"role": "user", "content": m["content"]})
            elif m["role"] == "assistant":
                msg = {"role": "assistant", "content": m.get("text") or ""}
                if m.get("tool_calls"):
                    msg["tool_calls"] = [{"id": c.id, "type": "function",
                                          "function": {"name": c.name, "arguments": json.dumps(c.args, ensure_ascii=False)}}
                                         for c in m["tool_calls"]]
                out.append(msg)
            else:
                out += [{"role": "tool", "tool_call_id": r["id"], "content": r["content"]} for r in m["results"]]
        return out

    @staticmethod
    def _parse_calls(message: dict) -> list[ToolCall]:
        calls = []
        for i, c in enumerate(message.get("tool_calls") or []):
            fn = c.get("function") or {}
            name = fn.get("name")
            raw = fn.get("arguments")
            if not name:
                raise ToolCallError("chamada de ferramenta inválida: veio sem nome.")
            if isinstance(raw, dict):
                args = raw
            else:
                try:
                    args = json.loads(raw or "{}")
                except (json.JSONDecodeError, TypeError) as e:
                    raise ToolCallError(f"chamada de ferramenta inválida: argumentos de {name} não são JSON "
                                        f"({str(raw)[:120]!r}).") from e
            if not isinstance(args, dict):
                raise ToolCallError(f"chamada de ferramenta inválida: argumentos de {name} não são um objeto.")
            calls.append(ToolCall(c.get("id") or f"call_{i}", name, args))
        return calls

    def turn(self, system: str, history: list[dict], tools: list[ToolSpec]) -> ModelTurn:
        body = {"model": self.model, "messages": self._messages(system, history), "stream": False,
                "max_tokens": self.max_tokens}
        if tools:
            body["tools"] = self._tools(tools)
            body["tool_choice"] = "auto"
        t0 = time.monotonic()
        data = self._request(f"{self.base_url}/chat/completions", body)
        seconds = time.monotonic() - t0
        try:
            choice = data["choices"][0]
            message = choice.get("message") or {}
        except (KeyError, IndexError, TypeError) as e:
            raise ServerUnreachable(f"resposta inesperada do servidor em {self.base_url}: {str(data)[:200]}") from e
        calls = self._parse_calls(message)
        finish = choice.get("finish_reason")
        stop = "tool_use" if calls else ("length" if finish == "length" else "end")
        u = data.get("usage") or {}
        usage = ({"input_tokens": u.get("prompt_tokens"), "output_tokens": u.get("completion_tokens")} if u else None)
        if not self._context_checked:
            self._context_checked = True
            self._check_ollama_context()
        return ModelTurn((message.get("content") or "").strip(), calls, stop, usage, seconds, raw=message)

    def _check_ollama_context(self) -> None:
        """O Ollama trunca o prompt em silêncio quando o contexto carregado é pequeno: avisamos."""
        root = self.base_url[:-3] if self.base_url.endswith("/v1") else self.base_url
        try:
            self._request(f"{root}/api/version", timeout=2)
            ps = self._request(f"{root}/api/ps", timeout=2)
        except LLMError:
            return
        for m in ps.get("models") or []:
            names = {m.get("name"), m.get("model")}
            if self.model in names or any(n and n.split(":")[0] == self.model.split(":")[0] for n in names):
                self.context_length = m.get("context_length")
                break
        if self.context_length and self.context_length < MIN_CONTEXT:
            self.context_warning = (f"o Ollama carregou o modelo com contexto de {self.context_length} tokens; "
                                    "respostas longas das ferramentas serão truncadas em silêncio. "
                                    "Veja docs/06-comparar-modelos.md para aumentar o contexto.")
