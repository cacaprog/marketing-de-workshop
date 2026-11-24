"""Escada de autonomia: shadow -> supervised -> guarded -> full.

O nível vem de config/autonomy.yaml (versionado, revisado). Para demonstrações, um
override global pode ser gravado em ops.autonomy_override (ex.: rodar tudo em shadow).
"""
from __future__ import annotations

from agentready.settings import autonomy

LEVELS = ["disabled", "shadow", "supervised", "guarded", "full"]


def get_override(con) -> str | None:
    con.execute("CREATE TABLE IF NOT EXISTS ops.autonomy_override (level VARCHAR)")
    r = con.execute("SELECT level FROM ops.autonomy_override").fetchone()
    return r[0] if r else None


def set_override(con, level: str | None) -> None:
    if level is not None and level not in LEVELS:
        raise ValueError(f"nível inválido: {level}. Use {LEVELS}")
    con.execute("CREATE TABLE IF NOT EXISTS ops.autonomy_override (level VARCHAR)")
    con.execute("DELETE FROM ops.autonomy_override")
    if level:
        con.execute("INSERT INTO ops.autonomy_override VALUES (?)", [level])


def decide(con, action: str, change_pct: float | None = None) -> dict:
    """Devolve o nível efetivo para esta ação concreta e o motivo."""
    cfg = autonomy()["actions"].get(action, {"level": "disabled", "reversibility": "R3"})
    level, reasons = cfg["level"], [f"nível configurado para {action}: {cfg['level']}"]
    esc = cfg.get("escalate_to_supervised_if", {})
    if level in ("guarded",) and change_pct is not None and abs(change_pct) > esc.get("abs_change_pct_gt", 1e9):
        level = "supervised"
        reasons.append(f"variação de {change_pct:+.0%} acima de {esc['abs_change_pct_gt']:.0%} -> rebaixado para supervised")
    override = get_override(con)
    if override and level != "disabled" and LEVELS.index(override) < LEVELS.index(level):
        reasons.append(f"override global ativo: {override}")
        level = override
    return {"level": level, "reversibility": cfg["reversibility"], "reasons": reasons}
