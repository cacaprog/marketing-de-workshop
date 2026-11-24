"""Compilador da camada semântica: (métricas, dimensões, janela) -> SQL determinístico contra a Gold.

O agente nunca escreve SQL. Ele pede métricas pelo nome; o compilador gera sempre
o mesmo SQL, com a fórmula oficial, no grão correto e com o guarda de frescor.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from agentready.db import rows
from agentready.settings import SEMANTIC_DIR, load_yaml


def model() -> dict:
    return load_yaml(SEMANTIC_DIR / "marketing.semantic.yaml")


@dataclass
class MetricRequest:
    metrics: list[str]
    group_by: list[str] = field(default_factory=lambda: ["campaign"])
    window_days: int = 14
    filters: dict[str, str] = field(default_factory=dict)


class SemanticError(ValueError):
    pass


def _measure_sql(name: str, sm: dict) -> str:
    m = sm["measures"][name]
    return f"{m['agg'].upper()}({m['expr']})"


def _metric_sql(name: str, sm: dict, seen: tuple = ()) -> str:
    if name in seen:
        raise SemanticError(f"métrica circular: {name}")
    metrics = sm["metrics"]
    if name not in metrics:
        if name in sm["measures"]:
            return _measure_sql(name, sm)
        raise SemanticError(f"métrica desconhecida: {name!r}. Disponíveis: {sorted(metrics)}")
    m = metrics[name]
    if m["type"] == "simple":
        return _measure_sql(m["measure"], sm)
    if m["type"] == "ratio":
        num = _metric_sql(m["numerator"], sm, seen + (name,))
        den = _metric_sql(m["denominator"], sm, seen + (name,))
        return f"(({num}) / NULLIF({den}, 0))"           # razão das somas, nunca média das razões
    if m["type"] == "derived":
        return "(" + re.sub(r"[a-z_]+", lambda t: _metric_sql(t.group(), sm, seen + (name,)), m["expr"]) + ")"
    raise SemanticError(f"tipo de métrica inválido: {m['type']}")


def _depends_on_conversions(name: str, sm: dict) -> bool:
    if name in sm["measures"]:
        return sm["measures"][name]["depends_on_conversions"]
    m = sm["metrics"][name]
    refs = {"simple": [m.get("measure")], "ratio": [m.get("numerator"), m.get("denominator")],
            "derived": re.findall(r"[a-z_]+", m.get("expr", ""))}[m["type"]]
    return any(_depends_on_conversions(r, sm) for r in refs)


def compile_sql(req: MetricRequest) -> str:
    sm = model()["semantic_model"]
    dims: list[str] = []
    for g in req.group_by:
        if g not in sm["dimensions"]:
            raise SemanticError(f"dimensão desconhecida: {g!r}. Disponíveis: {sorted(sm['dimensions'])}")
        dims += [d for d in sm["dimensions"][g] if d not in dims]
    select = [f"{_metric_sql(m, sm)} AS {m}" for m in req.metrics]
    where = [f"{sm['time_dimension']} >= current_date - INTERVAL {int(req.window_days)} DAY",
             f"{sm['time_dimension']} < current_date"]
    for k, v in req.filters.items():
        if k not in sum(sm["dimensions"].values(), []):
            raise SemanticError(f"filtro em coluna não exposta: {k}")
        where.append(f"{k} = '{str(v).replace(chr(39), '')}'")
    # Guarda de frescor: cada linha da Gold é cruzada com a saúde da sua fonte de conversões.
    # Se QUALQUER linha do grupo vier de fonte fora do SLA, métricas que dependem de
    # conversões viram NULL (desconhecido) — dado atrasado não é zero.
    group = f"\n  GROUP BY {', '.join(dims)}" if dims else ""
    inner = (f"SELECT {''.join(d + ', ' for d in dims)}{', '.join(select)},\n"
             f"         bool_or(h.status = 'stale') AS _stale, max(h.age_hours) AS conversions_age_hours\n"
             f"  FROM {sm['table']} t LEFT JOIN gold.source_health h\n"
             f"    ON h.dataset = 'conversions' AND h.partition = t.conversion_source\n"
             f"  WHERE {' AND '.join(where)}{group}")
    guarded = [f"CASE WHEN _stale THEN NULL ELSE {x} END AS {x}"
               if _depends_on_conversions(x, sm) else x for x in req.metrics]
    return (f"WITH m AS (\n  {inner}\n)\n"
            f"SELECT {''.join(d + ', ' for d in dims)}{', '.join(guarded)},\n"
            f"       CASE WHEN _stale THEN 'stale' ELSE 'fresh' END AS data_status, conversions_age_hours\n"
            f"FROM m" + (f"\nORDER BY {dims[0]}" if dims else ""))


def query(con, req: MetricRequest) -> tuple[str, list[dict]]:
    sql = compile_sql(req)
    return sql, rows(con, sql)


def _norm(s: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFD", s.lower()) if unicodedata.category(ch) != "Mn")


def interpret(question: str) -> MetricRequest:
    """Tradução determinística linguagem natural -> MetricRequest via sinônimos do modelo.

    Num produto real esta etapa é feita pelo LLM, mas o LLM só escolhe NOMES de
    métricas e dimensões — quem gera o SQL é sempre o compilador.
    """
    q = _norm(question)
    sm = model()["semantic_model"]
    found: list[tuple[int, str]] = []
    synonyms = sorted(((_norm(s), n) for n, m in sm["metrics"].items() for s in m.get("synonyms", [])),
                      key=lambda x: len(x[0]), reverse=True)    # o sinônimo mais longo vence
    for syn, name in synonyms:
        pos = q.find(syn)
        if pos >= 0:
            if name not in [f[1] for f in found]:
                found.append((pos, name))
            q = q[:pos] + " " * len(syn) + q[pos + len(syn):]
    if not found:
        raise SemanticError("nenhuma métrica oficial reconhecida na pergunta")
    metrics = [n for _, n in sorted(found)]
    group = ["channel"] if "por canal" in q else ["campaign"]
    win = re.search(r"(\d+)\s*dias", q)
    return MetricRequest(metrics=metrics, group_by=group, window_days=int(win.group(1)) if win else 14)
