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

KIND_STYLE = {"tool": ("dim", "🔧"), "thought": ("cyan", "💭"), "action": ("bold yellow", "⚡"),
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
