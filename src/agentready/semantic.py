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
    m = load_yaml(SEMANTIC_DIR / "marketing.semantic.yaml")
    validate_model(m)
    return m


def validate_model(m: dict) -> None:
    """Regras de "não se aplica" só podem citar colunas de dimensão e regras de domínio que existem."""
    sm = m["semantic_model"]
    cols = {c for cs in sm["dimensions"].values() for c in cs}
    rules = {r["id"] for r in m.get("domain_model", {}).get("rules", [])}
    for name, metric in sm["metrics"].items():
        na = metric.get("not_applicable")
        if not na:
            continue
        bad = [c for c in (na.get("when") or {}) if c not in cols]
        if bad or not na.get("when"):
            raise SemanticError(f"métrica {name}: not_applicable.when usa coluna inexistente {bad or '(vazio)'}; "
                                f"colunas disponíveis: {sorted(cols)}")
        if na.get("rule") not in rules:
            raise SemanticError(f"métrica {name}: not_applicable.rule {na.get('rule')!r} não existe em domain_model.rules")
        if not na.get("reason"):
            raise SemanticError(f"métrica {name}: not_applicable.reason é obrigatório")


@dataclass
class MetricRequest:
    metrics: list[str]
    group_by: list[str] = field(default_factory=lambda: ["campaign"])
    window_days: int = 14
    filters: dict[str, str] = field(default_factory=dict)


class SemanticError(ValueError):
    pass


def _measure_sql(name: str, sm: dict, flt: str | None = None) -> str:
    m = sm["measures"][name]
    return f"{m['agg'].upper()}({m['expr']})" + (f" FILTER (WHERE {flt})" if flt else "")


def _q(v) -> str:
    return "'" + str(v).replace("'", "''") + "'"


def _na_cond(name: str, sm: dict) -> str | None:
    """Condição SQL em que a métrica NÃO se aplica (regra declarada no modelo semântico), ou None."""
    na = sm["metrics"].get(name, {}).get("not_applicable")
    if not na:
        return None
    return " OR ".join(f"t.{col} IN ({', '.join(_q(v) for v in vals)})" for col, vals in na["when"].items())


def _metric_sql(name: str, sm: dict, seen: tuple = (), flt: str | None = None) -> str:
    if name in seen:
        raise SemanticError(f"métrica circular: {name}")
    metrics = sm["metrics"]
    if name not in metrics:
        if name in sm["measures"]:
            return _measure_sql(name, sm, flt)
        raise SemanticError(f"métrica desconhecida: {name!r}. Disponíveis: {sorted(metrics)}")
    m = metrics[name]
    if m["type"] == "simple":
        return _measure_sql(m["measure"], sm, flt)
    if m["type"] == "ratio":
        num = _metric_sql(m["numerator"], sm, seen + (name,), flt)
        den = _metric_sql(m["denominator"], sm, seen + (name,), flt)
        return f"(({num}) / NULLIF({den}, 0))"           # razão das somas, nunca média das razões
    if m["type"] == "derived":
        return "(" + re.sub(r"[a-z_]+", lambda t: _metric_sql(t.group(), sm, seen + (name,), flt), m["expr"]) + ")"
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
    select, na_cols = [], []
    for m in req.metrics:
        cond = _na_cond(m, sm)
        # Regra no dado: a métrica é calculada só sobre as linhas em que ela se aplica.
        select.append(f"{_metric_sql(m, sm, flt=f'NOT ({cond})' if cond else None)} AS {m}")
        if cond:
            na_cols += [f"COUNT(*) FILTER (WHERE NOT ({cond})) AS _{m}_ok",
                        f"COUNT(DISTINCT t.campaign_id) FILTER (WHERE {cond}) AS _{m}_excl"]
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
    inner = (f"SELECT {''.join(d + ', ' for d in dims)}{', '.join(select + na_cols)},\n"
             f"         bool_or(h.status = 'stale') AS _stale, max(h.age_hours) AS conversions_age_hours\n"
             f"  FROM {sm['table']} t LEFT JOIN gold.source_health h\n"
             f"    ON h.dataset = 'conversions' AND h.partition = t.conversion_source\n"
             f"  WHERE {' AND '.join(where)}{group}")
    guarded = []
    for x in req.metrics:
        stale = _depends_on_conversions(x, sm)
        na = sm["metrics"].get(x, {}).get("not_applicable")
        if not na:
            guarded.append(f"CASE WHEN _stale THEN NULL ELSE {x} END AS {x}" if stale else x)
            continue
        # Três estados: número · desconhecido (fonte atrasada, Princípio III) · não se aplica (regra de domínio).
        st = " WHEN _stale THEN NULL" if stale else ""
        ss = " WHEN _stale THEN 'desconhecido'" if stale else ""
        label = "/".join(str(v) for vals in na["when"].values() for v in vals)
        guarded += [f"CASE WHEN _{x}_ok = 0 THEN NULL{st} ELSE {x} END AS {x}",
                    f"CASE WHEN _{x}_ok = 0 THEN 'nao_se_aplica'{ss} ELSE 'ok' END AS {x}_status",
                    f"CASE WHEN _{x}_ok = 0 THEN {_q(na['reason'])} WHEN _{x}_excl > 0 THEN "
                    f"'exclui ' || _{x}_excl || ' campanha(s) de {label}' END AS {x}_motivo"]
    return (f"WITH m AS (\n  {inner}\n)\n"
            f"SELECT {''.join(d + ', ' for d in dims)}{', '.join(guarded)},\n"
            f"       CASE WHEN _stale THEN 'stale' ELSE 'fresh' END AS data_status, conversions_age_hours\n"
            f"FROM m" + (f"\nORDER BY {dims[0]}" if dims else ""))


NA_TEXT = "não se aplica"


def display(result_rows: list[dict]) -> list[dict]:
    """Para pessoas: métrica com status nao_se_aplica vira o texto "não se aplica" (nunca NULL, que é
    "desconhecido"); as colunas *_status e *_motivo saem da tabela (o motivo vai numa nota, via motivos())."""
    out = []
    for r in result_rows:
        d = dict(r)
        for k, v in r.items():
            if k.endswith("_status") and v == "nao_se_aplica" and k[:-7] in d:
                d[k[:-7]] = NA_TEXT
        out.append({k: v for k, v in d.items() if not (k.endswith("_status") and k != "data_status")
                    and not k.endswith("_motivo")})
    return out


def motivos(result_rows: list[dict]) -> list[str]:
    seen: list[str] = []
    for r in result_rows:
        for k, v in r.items():
            if k.endswith("_motivo") and v and v not in seen:
                seen.append(v)
    return seen


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
