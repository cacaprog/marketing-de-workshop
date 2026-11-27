"""Perguntas de negócio respondidas lado a lado, com e sem a camada de contexto (005, US5) — e o chat (US6).

As respostas oficiais vêm de REGRAS em config/perguntas.yaml, resolvidas na hora contra o cenário pela
camada semântica, pela saúde das fontes e pelas regras de domínio. O modelo responde pela ferramenta
`responder` nas duas condições, e o veredito é calculado de forma determinística.
"""
from __future__ import annotations

import json
import statistics
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from agentready import agent, llm, semantic, toolsets, tracing, ui
from agentready.db import connect, rows
from agentready.settings import CONFIG_DIR, guardrails, load_yaml

QUESTIONS_FILE = CONFIG_DIR / "perguntas.yaml"
VERDICTS = ("certa", "desconhecido_correto", "errada", "inventou_numero", "sem_resposta", "falhou")
VERDICT_LABEL = {"certa": "CERTA", "desconhecido_correto": "DESCONHECIDO CORRETO", "errada": "ERRADA",
                 "inventou_numero": "INVENTOU NÚMERO", "sem_resposta": "SEM RESPOSTA", "falhou": "FALHOU"}
VERDICT_STYLE = {"certa": "bold green", "desconhecido_correto": "bold green", "errada": "bold red",
                 "inventou_numero": "bold red", "sem_resposta": "yellow", "falhou": "yellow"}
STATUS_LABEL = {"desconhecido": "desconhecido", "nao_se_aplica": "não se aplica"}
MONEY = {"net_revenue", "cac", "spend"}
MAX_TURNS = 8
SYSTEM = ("Você é o agente de otimização de orçamento de mídia da Aurora Cosméticos.\n"
          "Responda à pergunta de negócio usando as ferramentas e registre a resposta com `responder`.")
CHAT_SYSTEM = ("Você é o agente de otimização de orçamento de mídia da Aurora Cosméticos.\n"
               "Responda às perguntas de negócio usando somente as ferramentas disponíveis, em português.")


class PerguntaInvalida(ValueError):
    pass


@dataclass
class Question:
    id: str
    texto: str
    mostra: str
    regra: dict


@dataclass
class Official:
    status: str
    valor: float | None = None
    campanhas: list[str] = field(default_factory=list)


# ------------------------------------------------------------------ carga e validação

def carregar(path: Path | None = None) -> tuple[dict, list[Question]]:
    raw = load_yaml(path or QUESTIONS_FILE)
    sm = semantic.model()
    metrics = set(sm["semantic_model"]["metrics"])
    rules = {r["id"] for r in sm["domain_model"]["rules"]}
    from agentready.generate import CAMPAIGNS
    camps = {c[0] for c in CAMPAIGNS}
    qs = []
    for q in raw["perguntas"]:
        r = q["resposta_oficial"]
        tipo = r.get("tipo")
        bad = None
        if tipo == "metrica":
            bad = (f"métrica desconhecida {r.get('metrica')!r}" if r.get("metrica") not in metrics else
                   f"campanha desconhecida {r.get('campanha')!r}" if r.get("campanha") not in camps | {None} else None)
        elif tipo == "desconhecido_se_atrasado":
            bad = f"campanha desconhecida {r.get('campanha')!r}" if r.get("campanha") not in camps else None
        elif tipo == "nao_se_aplica":
            bad = f"regra de domínio desconhecida {r.get('regra')!r}" if r.get("regra") not in rules else None
        elif tipo == "campanhas":
            bad = (f"critério desconhecido {r.get('criterio')!r}"
                   if r.get("criterio") not in ("roas_abaixo_do_piso", "fonte_atrasada") else None)
        else:
            bad = f"tipo de resposta desconhecido {tipo!r}"
        if bad:
            raise PerguntaInvalida(f"pergunta {q.get('id')!r} em {QUESTIONS_FILE.name}: {bad}")
        qs.append(Question(q["id"], q["texto"], q.get("mostra", ""), r))
    return raw, qs


# ------------------------------------------------------------------ resposta oficial

def _metric(con, metric: str, campaign: str | None, window: int):
    if campaign:
        rs = semantic.query(con, semantic.MetricRequest([metric], ["campaign"], window))[1]
        r = next((x for x in rs if x["campaign_id"] == campaign), None)
        return r[metric] if r else None
    rs = semantic.query(con, semantic.MetricRequest([metric], [], window))[1]
    return rs[0][metric] if rs else None


def _stale_campaigns(con) -> set[str]:
    stale = {r["partition"] for r in rows(con, "SELECT partition FROM gold.source_health "
                                               "WHERE dataset='conversions' AND status='stale'")}
    return {r["campaign_id"] for r in rows(con, "SELECT campaign_id, conversion_source FROM gold.dim_campaign")
            if r["conversion_source"] in stale}


def resolver(q: Question, con) -> Official:
    r = q.regra
    tipo = r["tipo"]
    if tipo == "nao_se_aplica":
        return Official("nao_se_aplica")
    if tipo == "desconhecido_se_atrasado":
        if r["campanha"] in _stale_campaigns(con):
            return Official("desconhecido")
        v = _metric(con, "net_revenue", r["campanha"], r.get("janela_dias", 7))
        return Official("valor", v) if v is not None else Official("desconhecido")
    if tipo == "metrica":
        v = _metric(con, r["metrica"], r.get("campanha"), r.get("janela_dias", 14))
        return Official("valor", round(float(v), 4)) if v is not None else Official("desconhecido")
    if r["criterio"] == "fonte_atrasada":
        return Official("valor", None, sorted(_stale_campaigns(con)))
    floor = guardrails()["optimization"]["roas_floor"]
    perf = semantic.query(con, semantic.MetricRequest(["roas"], ["campaign"], r.get("janela_dias", 14)))[1]
    # A regra vem do dado (006): status "ok" = a métrica se aplica E a fonte está fresca. Nada de objetivo
    # escrito aqui; quem decide onde o ROAS se aplica é o modelo semântico.
    return Official("valor", None, sorted(p["campaign_id"] for p in perf
                                          if p.get("roas_status") == "ok" and p["roas"] < floor))


def resolver_todas(con=None) -> list[tuple[Question, Official]]:
    own = con is None
    con = con or connect()
    try:
        _, qs = carregar()
        return [(q, resolver(q, con)) for q in qs]
    finally:
        if own:
            con.close()


# ------------------------------------------------------------------ veredito

def veredito(oficial: Official, ans: dict | None, tol: float) -> str:
    if ans is None:
        return "sem_resposta"
    status = ans.get("status")
    if oficial.status in ("desconhecido", "nao_se_aplica"):
        if status == oficial.status:
            return "desconhecido_correto" if status == "desconhecido" else "certa"
        if status == "valor" and (ans.get("valor") is not None or ans.get("campanhas")):
            return "inventou_numero"
        return "errada"
    if status != "valor":
        return "errada"
    if oficial.campanhas or oficial.valor is None:
        got = {str(c).strip().upper() for c in ans.get("campanhas") or []}
        return "certa" if got == set(oficial.campanhas) else "errada"
    v = ans.get("valor")
    if not isinstance(v, (int, float)):
        return "errada"
    ref = oficial.valor
    return "certa" if abs(v - ref) <= tol * max(abs(ref), 1e-9) else "errada"


# ------------------------------------------------------------------ uma pergunta, uma condição

def responder_pergunta(spec: llm.BrainSpec, condition: str, q: Question, oficial: Official, con, tol: float) -> dict:
    ts = toolsets.leitura_sem(con, responder=True) if condition == toolsets.SEM_CONTEXTO else toolsets.leitura_com(True)
    rep = agent.RunReport(f"pergunta {q.id} ({spec.label}, {condition})")
    with tracing.span("agent.run", **{"gen_ai.agent.name": "business-question", "agent.brain": spec.kind,
                                      "agent.condition": condition, "question.id": q.id, "user.request": q.texto}):
        agent.LLMBrain(llm.adapter_for(spec), ts, system=SYSTEM, max_turns=MAX_TURNS,
                       require_tool=False).run(con, q.texto, rep)
        rep.trace_id = tracing.current_trace_id()
    tracing.flush()
    last = next((s.text for s in reversed(rep.steps) if s.kind in ("summary", "thought")), "")
    v = "falhou" if rep.outcome == "falhou" else veredito(oficial, rep.answer, tol)
    a = rep.answer or {}
    return {"status": a.get("status"), "valor": a.get("valor"), "campanhas": a.get("campanhas") or [],
            "explicacao": a.get("explicacao") or "", "veredito": v, "failure": rep.failure,
            "trace_id": rep.trace_id, "seconds": rep.seconds, "last_text": last[:600]}


def _run_set(spec: llm.BrainSpec, qs: list[Question], tol: float, on_question=None) -> dict:
    from agentready.compare import fresh_scenario
    fresh_scenario()
    con = connect()
    out = []
    try:
        for i, q in enumerate(qs, 1):
            of = resolver(q, con)
            item = {"id": q.id, "texto": q.texto, "mostra": q.mostra, "metrica": q.regra.get("metrica"),
                    "oficial": asdict(of), "respostas": {}}
            for cond in (toolsets.SEM_CONTEXTO, toolsets.COM_CONTEXTO):
                item["respostas"][cond] = responder_pergunta(spec, cond, q, of, con, tol)
            out.append(item)
            if on_question:
                on_question(i, len(qs), item)
    finally:
        con.close()
    return {"questions": out, "totals": _totals(out)}


def _totals(items: list[dict]) -> dict:
    return {c: {v: sum(1 for it in items if it["respostas"].get(c, {}).get("veredito") == v) for v in VERDICTS}
            for c in (toolsets.SEM_CONTEXTO, toolsets.COM_CONTEXTO)}


def _select(qs: list[Question], ids: str | None) -> list[Question]:
    if not ids:
        return qs
    want = [i.strip() for i in ids.split(",") if i.strip()]
    unknown = [i for i in want if i not in {q.id for q in qs}]
    if unknown:
        raise PerguntaInvalida(f"pergunta desconhecida: {', '.join(unknown)}")
    return [q for q in qs if q.id in want]


def results_dir() -> Path:
    from agentready.compare import results_dir as rd
    return rd()


def rodar(spec: llm.BrainSpec, ids: str | None = None, pause: bool = True) -> Path:
    raw, qs = carregar()
    qs = _select(qs, ids)
    recorded = datetime.now()

    def show(i, n, item):
        ui.pergunta_panel(i, n, item)
        if pause and i < n:
            ui.pause()
    doc = {"format": "agentready-perguntas/1", "recorded_at": recorded.isoformat(timespec="seconds"),
           "brain": spec.label, "question_set_version": raw["version"]}
    doc |= _run_set(spec, qs, raw["tolerancia_relativa"], show)
    ui.perguntas_totais(doc["totals"])
    path = results_dir() / f"perguntas-{recorded:%Y%m%d-%H%M%S}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    ui.console.print(f"Gravado em {path} — para reapresentar sem modelo nem rede: "
                     f"agentready perguntas --mostrar {path}")
    from agentready.compare import fresh_scenario
    fresh_scenario()
    return path


def mostrar(path: str, ids: str | None = None, pause: bool = True) -> None:
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    if doc.get("format") != "agentready-perguntas/1":
        raise PerguntaInvalida(f"{path} não é um arquivo de perguntas gravado pelo agentready.")
    items = doc["questions"]
    if ids:
        want = {i.strip() for i in ids.split(",")}
        items = [it for it in items if it["id"] in want]
    ui.console.print(f"[bold]Gravado em {doc['recorded_at']} com {doc['brain']}[/] "
                     f"[dim](perguntas v{doc['question_set_version']}; reapresentação, sem modelo)[/]")
    for i, it in enumerate(items, 1):
        ui.pergunta_panel(i, len(items), it)
        if pause and i < len(items):
            ui.pause()
    ui.perguntas_totais(_totals(items))


# ------------------------------------------------------------------ comparação em modo perguntas

def cmd_compare(specs: list[llm.BrainSpec], runs: int, yes: bool) -> int:
    from agentready.compare import probe
    raw, qs = carregar()
    skipped, ok = [], []
    for s in specs:
        reason = ("as perguntas precisam de um modelo de linguagem; para a camada semântica determinística use "
                  "agentready ask." if s.kind == "rules" else probe(s))
        (skipped.append({"brain": s.label, "reason": reason}) if reason else ok.append(s))
    lines = [f"Plano (perguntas): {', '.join(s.label for s in ok) or 'nenhum cérebro'} · {len(qs)} perguntas × "
             f"2 condições × {runs} execução(ões).", "A comparação recria o cenário a cada execução (como o setup)."]
    if any(s.kind == "claude" for s in ok):
        lines.append("Usa a API da Anthropic (cobrada por token).")
    for line in lines:
        ui.console.print(line)
    if not yes:
        try:
            if input("Continuar? [s/N] ").strip().lower() not in ("s", "sim", "y", "yes"):
                return 1
        except EOFError:
            return 1
    started = datetime.now()
    doc = {"format": "agentready-comparacao-perguntas/1", "started_at": started.isoformat(timespec="seconds"),
           "question_set_version": raw["version"], "brains": [s.label for s in specs], "runs_per_brain": runs,
           "skipped": skipped, "runs": [], "summary": []}
    path = results_dir() / f"comparacao-perguntas-{started:%Y%m%d-%H%M%S}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        for s in ok:
            for i in range(1, runs + 1):
                r = _run_set(s, qs, raw["tolerancia_relativa"])
                doc["runs"].append({"brain": s.label, "index": i, **r})
                ui.console.print(f"{s.label} · execução {i}/{runs} · sem contexto: "
                                 f"{r['totals']['sem_contexto']['certa']} certas · com contexto: "
                                 f"{r['totals']['com_contexto']['certa']} certas")
                doc["summary"] = _summary(doc["runs"])
                path.write_text(json.dumps(doc, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    finally:
        doc["finished_at"] = datetime.now().isoformat(timespec="seconds")
        doc["summary"] = _summary(doc["runs"])
        path.write_text(json.dumps(doc, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        from agentready.compare import fresh_scenario
        fresh_scenario()
    ui.perguntas_table(doc["summary"])
    for s in skipped:
        ui.console.print(f"[yellow]Pulado:[/] {s['brain']} — {s['reason']}")
    ui.console.print(f"Resultados: {path}")
    return 0 if doc["runs"] else 2


def _summary(runs: list[dict]) -> list[dict]:
    out = []
    for b in dict.fromkeys(r["brain"] for r in runs):
        for c in (toolsets.SEM_CONTEXTO, toolsets.COM_CONTEXTO):
            rs = [r["totals"][c] for r in runs if r["brain"] == b]
            out.append({"brain": b, "condition": c, "runs": len(rs),
                        **{v: round(statistics.mean(t[v] for t in rs), 2) for v in VERDICTS}})
    return out


# ------------------------------------------------------------------ chat (US6)

def conversar(spec: llm.BrainSpec, condition: str, read=input) -> None:
    label = ("SEM CONTEXTO (dados brutos da Bronze)" if condition == toolsets.SEM_CONTEXTO
             else "COM CONTEXTO (métricas oficiais e saúde dos dados)")
    short = "sem contexto" if condition == toolsets.SEM_CONTEXTO else "com contexto"
    ui.console.print(f"[bold]Conversa com {spec.label} · {label}[/]  [dim](digite `sair` para terminar)[/]")
    con = connect()
    try:
        ts = toolsets.leitura_sem(con) if condition == toolsets.SEM_CONTEXTO else toolsets.leitura_com()
        brain = agent.LLMBrain(llm.adapter_for(spec), ts, system=CHAT_SYSTEM, require_tool=False)
        history: list[dict] = []
        while True:
            try:
                text = read("você> ").strip()
            except (EOFError, KeyboardInterrupt):
                ui.console.print()
                break
            if not text:
                continue
            if text.lower() in ("sair", "exit", "quit"):
                break
            rep = agent.RunReport("chat")
            with tracing.span("agent.run", **{"gen_ai.agent.name": "chat", "agent.brain": spec.kind,
                                              "agent.condition": condition, "user.request": text}):
                history = brain.run(con, text, rep, history)
            tracing.flush()
            for s in rep.steps:
                if s.kind == "tool":
                    ui.console.print(f"  [dim]🔧 {s.text[:160]}[/]")
            answer = rep.failure or next((s.text for s in reversed(rep.steps) if s.kind in ("summary", "thought")), "")
            ui.console.print(f"[bold]{short}>[/] {answer or '(sem resposta)'}")
    finally:
        con.close()
