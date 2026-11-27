"""Helpers de apresentação no terminal (rich)."""
from __future__ import annotations

import sys

from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table
from rich.tree import Tree

from agentready.capabilities import brl

console = Console(highlight=False)
PAUSE = sys.stdin.isatty()

KIND_STYLE = {"tool": ("dim", "🔧"), "thought": ("cyan", "💭"), "action": ("bold yellow", "⚡"), "warning": ("bold red", "⚠"),
              "refusal": ("bold green", "🛑"), "summary": ("bold", "✅")}
STATUS_STYLE = {"executed": "green", "queued_for_approval": "yellow", "shadow_logged": "blue",
                "rejected": "bold red", "disabled": "red"}


def pause(msg: str = "Enter para continuar") -> None:
    if PAUSE:
        console.input(f"[dim]↵ {msg}[/]")
    console.print()


def block(n: int | str, title: str, problem: str) -> None:
    console.rule(f"[bold]Bloco {n} · {title}")
    console.print(Panel(problem, title="Problema", border_style="red", padding=(0, 1)))


def deliverable(text: str) -> None:
    console.print(Panel(text, title="Entregável do bloco", border_style="green", padding=(0, 1)))


def note(text: str) -> None:
    console.print(f"[dim]›[/] {text}")


def sql(text: str) -> None:
    console.print(Syntax(text.strip(), "sql", theme="ansi_dark", word_wrap=True))


def table(rows: list[dict], cols: list[str] | None = None, title: str | None = None, fmt: dict | None = None) -> None:
    if not rows:
        note("(sem linhas)")
        return
    cols = cols or list(rows[0].keys())
    fmt = fmt or {}
    t = Table(title=title, title_justify="left", header_style="bold", show_lines=False)
    for c in cols:
        t.add_column(c, overflow="fold")
    for r in rows:
        t.add_row(*[fmt[c](r.get(c)) if c in fmt else _cell(r.get(c)) for c in cols])
    console.print(t)


def _cell(v) -> str:
    if v is None:
        return "[magenta]NULL[/]"
    if v == "não se aplica":                     # regra de domínio no dado (006): não é dado desconhecido
        return "[blue]não se aplica[/]"
    if isinstance(v, float):
        return f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    if v in ("stale", "barred", False):
        return f"[red]{v}[/]"
    if v in ("fresh", "passed", True):
        return f"[green]{v}[/]"
    return str(v)


def report(rep) -> None:
    console.print(f"[bold]{rep.agent}[/]  [dim]trace {rep.trace_id}[/]")
    for s in rep.steps:
        style, icon = KIND_STYLE.get(s.kind, ("", "•"))
        text = s.text
        res = s.data.get("result")
        if res:
            text = text.replace(res["status"], f"[{STATUS_STYLE.get(res['status'], '')}]{res['status']}[/]", 1)
        console.print(f" {icon} [{style}]{text}[/]" if s.kind != "action" or not res else f" {icon} {text}")


def checks(result: dict) -> None:
    t = Table(title=f"Pré-condições · {result['action']}({result['campaign_id']})", title_justify="left")
    t.add_column("pré-condição")
    t.add_column("ok")
    t.add_column("detalhe", overflow="fold")
    for c in result["preconditions"]:
        t.add_row(c["id"], "[green]✓[/]" if c["passed"] else "[red]✗[/]", c["detail"])
    console.print(t)


def trace_tree(nodes: list[dict]) -> None:
    def add(parent, n):
        err = n["status"] == "ERROR"
        a = n["attributes"]
        extra = []
        for k in ("decision.status", "autonomy.level", "campaign_id", "data.stale_sources", "preconditions.failed",
                  "resource.uri", "trust", "semantic.model_version", "gen_ai.usage.output_tokens"):
            if k in a:
                extra.append(f"{k}={a[k]}")
        label = f"[{'red' if err else 'green'}]{n['name']}[/] [dim]{' · '.join(extra)}[/]"
        node = parent.add(label)
        for c in n["children"]:
            add(node, c)
    for root in nodes:
        t = Tree(f"[bold]{root['name']}[/] [dim]{root['trace_id']}[/]")
        for c in root["children"]:
            add(t, c)
        console.print(t)


def budgets(rows_: list[dict], title: str = "Estado vivo da plataforma (ops.campaigns)") -> None:
    table(rows_, ["campaign_id", "daily_budget_brl", "status"], title=title,
          fmt={"daily_budget_brl": brl, "status": lambda s: f"[red]{s}[/]" if s != "active" else s})


# ------------------------------------------------------------------ comparação de modelos (005)

COND_LABEL = {"sem_contexto": "sem contexto", "com_contexto": "com contexto"}


def _num(x: float, money: bool) -> str:
    if money:
        return "R$ " + f"{x:,.0f}".replace(",", ".")
    return str(int(x)) if float(x).is_integer() else f"{x:.1f}".replace(".", ",")


def _stat(d: dict | None, money: bool = False) -> str:
    if not d:
        return "—"
    s = _num(d["mean"], money)
    return s if d["min"] == d["max"] else f"{s} ({_num(d['min'], money)}–{_num(d['max'], money)})"


def comparison_table(summary: list[dict], title: str = "Comparação: o mesmo cérebro com e sem a camada de contexto") -> None:
    t = Table(title=title, title_style="bold", header_style="bold")
    for c in ("Cérebro", "Condição", "Execuções", "Lucrativas pausadas", "Ações c/ dado atrasado",
              "R$/dia fora dos guardrails", "Seguiu a injeção", "R$/dia em risco", "Pedidos de aprovação",
              "Falhas", "Sem ação"):
        t.add_column(c, justify="left" if c in ("Cérebro", "Condição") else "right")
    for r in summary:
        scored = r.get("followed_injection") or {"k": 0, "n": 0}
        bad = "red" if r["condition"] == "sem_contexto" else "green"
        t.add_row(r["brain"], f"[{bad}]{COND_LABEL.get(r['condition'], r['condition'])}[/]", str(r["runs"]),
                  _stat(r["protected_paused"]), _stat(r["stale_actions"]),
                  _stat(r["brl_outside_guardrails"], True),
                  f"{scored['k']} de {scored['n']}" if scored["n"] else "—",
                  _stat(r["brl_at_risk"], True), _stat(r["approval_requests"]),
                  str(r["failed"]), str(r["no_action"]))
    console.print(t)
    console.print("[dim]Médias sobre execuções que terminaram (ok ou sem ação). Poucas execuções ilustram, não medem: "
                  "resultados de modelos de linguagem variam a cada execução.[/]")


# ------------------------------------------------------------------ perguntas lado a lado (005, US5)

def _fmt_value(v, metric: str | None) -> str:
    if v is None:
        return "—"
    v = float(v)
    if metric == "roas":
        return f"{v:.2f}".replace(".", ",")
    if abs(v) >= 1000:
        return "R$ " + f"{v:,.0f}".replace(",", ".")
    return "R$ " + f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _fmt_answer(a: dict, metric: str | None, set_question: bool = False) -> str:
    """Pergunta de número mostra o número; pergunta de lista de campanhas mostra a lista."""
    from agentready.perguntas import STATUS_LABEL
    st = a.get("status")
    if st in STATUS_LABEL:
        return STATUS_LABEL[st]
    if st != "valor":
        return "(sem resposta registrada)"
    if set_question:
        return ", ".join(a.get("campanhas") or []) or "nenhuma campanha"
    if a.get("valor") is not None:
        return _fmt_value(a["valor"], metric)
    return ", ".join(a.get("campanhas") or []) or "(sem número)"


def diferenca_oficial(oficial: dict, resposta: dict) -> str | None:
    """Mostra o quanto um número difere do oficial, mesmo quando cabe na tolerância ("certa")."""
    ref, v = oficial.get("valor"), resposta.get("valor")
    if (oficial.get("status") != "valor" or resposta.get("status") != "valor" or oficial.get("campanhas")
            or not isinstance(ref, (int, float)) or not isinstance(v, (int, float)) or ref == 0):
        return None
    pct = (v - ref) / abs(ref)
    if abs(pct) < 0.0005:
        return "igual ao oficial"
    return "diferença do oficial: " + f"{pct * 100:+.1f}%".replace(".", ",")


def pergunta_panel(i: int, n: int, item: dict) -> None:
    from rich.columns import Columns

    from agentready.perguntas import VERDICT_LABEL, VERDICT_STYLE
    metric = item.get("metrica")
    of = item["oficial"]
    set_q = bool(of.get("campanhas")) or (of.get("status") == "valor" and of.get("valor") is None)
    console.rule(f"[bold]Pergunta {i}/{n}[/]")
    console.print(f"[bold]{item['texto']}[/]")
    console.print(f"Resposta oficial: [bold cyan]{_fmt_answer(of, metric, set_q)}[/]")
    panels = []
    for cond, title in (("sem_contexto", "sem contexto"), ("com_contexto", "com contexto")):
        a = item["respostas"].get(cond, {})
        v = a.get("veredito", "falhou")
        why = a.get("explicacao") or a.get("failure") or (a.get("last_text") or "")[:160]
        diff = diferenca_oficial(of, a)
        body = (f"[bold]{_fmt_answer(a, metric, set_q)}[/]" + (f"  [yellow]{diff}[/]" if diff else "")
                + f"\n[dim]{why}[/]\n\n[{VERDICT_STYLE[v]}]{VERDICT_LABEL[v]}[/]")
        panels.append(Panel(body, title=title, width=max(38, min(60, console.width // 2 - 2))))
    console.print(Columns(panels))
    if item.get("mostra"):
        console.print(f"[dim]O que mostra:[/] {item['mostra']}")


def perguntas_totais(totals: dict) -> None:
    from agentready.perguntas import VERDICT_LABEL
    console.rule()
    for cond, label in (("sem_contexto", "sem contexto"), ("com_contexto", "com contexto")):
        t = totals.get(cond, {})
        console.print(f"[bold]{label}:[/] " + " · ".join(f"{t.get(k, 0)} {VERDICT_LABEL[k].lower()}"
                                                       for k in VERDICT_LABEL))


def perguntas_table(summary: list[dict]) -> None:
    from agentready.perguntas import VERDICT_LABEL
    t = Table(title="Perguntas de negócio: o mesmo modelo com e sem a camada de contexto", title_style="bold",
              header_style="bold")
    t.add_column("Cérebro")
    t.add_column("Condição")
    t.add_column("Execuções", justify="right")
    for k, lab in VERDICT_LABEL.items():
        t.add_column(lab.capitalize(), justify="right")
    for r in summary:
        bad = "red" if r["condition"] == "sem_contexto" else "green"
        t.add_row(r["brain"], f"[{bad}]{COND_LABEL[r['condition']]}[/]", str(r["runs"]),
                  *[_num(r[k], False) for k in VERDICT_LABEL])
    console.print(t)
    console.print("[dim]Médias de perguntas por execução (8 perguntas). Poucas execuções ilustram, não medem.[/]")
