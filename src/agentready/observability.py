"""Os 5 pilares de observabilidade de dados: Frescor, Volume, Distribuição, Esquema e Linhagem.

Contratos pegam o que é INVÁLIDO. Observabilidade pega o que é VÁLIDO, MAS ERRADO
(ex.: valores que passaram a vir em centavos continuam sendo números >= 0).
"""
from __future__ import annotations

from datetime import datetime

from agentready import contracts
from agentready.db import rows

VOLUME_BAND = (0.5, 1.5)        # lote fora de 50%-150% da mediana histórica
DISTRIBUTION_BAND = (0.5, 2.0)  # ticket médio do lote fora de 0,5x-2x da mediana histórica


def freshness(con) -> list[dict]:
    return [{"pillar": "frescor", "target": f"{h['dataset']}/{h['partition']}", "ok": h["status"] == "fresh",
             "detail": f"última carga ok há {h['age_hours']}h (SLA {h['sla_hours']:.0f}h)"}
            for h in rows(con, "SELECT * FROM gold.source_health ORDER BY dataset, partition")]


def volume(con) -> list[dict]:
    """Linhas recebidas por fonte para o DIA DE NEGÓCIO de ontem vs mediana dos 14 dias anteriores (Bronze)."""
    out = []
    for r in rows(con, """
        WITH d AS (SELECT s.source, CAST(t.day AS DATE) AS day, COUNT(c.source) AS n
                   FROM (SELECT DISTINCT source FROM bronze.conversions WHERE source IS NOT NULL) s
                   CROSS JOIN range(CAST(current_date - 15 AS TIMESTAMP), CAST(current_date AS TIMESTAMP), INTERVAL 1 DAY) t(day)
                   LEFT JOIN bronze.conversions c ON c.source = s.source
                        AND TRY_CAST(c.converted_at AS DATE) = CAST(t.day AS DATE)
                   GROUP BY ALL)
        SELECT source, max(n) FILTER (WHERE day = current_date - 1) AS n,
               median(n) FILTER (WHERE day < current_date - 1 AND n > 0) AS baseline
        FROM d GROUP BY source ORDER BY source"""):
        ratio = r["n"] / r["baseline"] if r["baseline"] else 1
        out.append({"pillar": "volume", "target": f"conversions/{r['source']}",
                    "ok": VOLUME_BAND[0] <= ratio <= VOLUME_BAND[1],
                    "detail": f"ontem: {r['n']} linhas recebidas vs mediana {r['baseline']:.0f} ({ratio:.1f}x)"})
    return out


def distribution_by_batch(con, table: str = "silver.conversions") -> list[dict]:
    return rows(con, f"""
        WITH b AS (SELECT source, batch_id, max(ingested_at) AS ing, avg(order_value_brl) AS avg_ticket
                   FROM {table} GROUP BY ALL),
             base AS (SELECT source, median(avg_ticket) AS med FROM b GROUP BY source)
        SELECT b.*, base.med, b.avg_ticket / base.med AS ratio FROM b JOIN base USING (source)
        ORDER BY ing DESC""")


def distribution(con) -> list[dict]:
    out, seen = [], set()
    for r in distribution_by_batch(con):
        if r["source"] in seen:
            continue
        seen.add(r["source"])
        out.append({"pillar": "distribuição", "target": f"conversions/{r['source']}.order_value_brl",
                    "ok": DISTRIBUTION_BAND[0] <= r["ratio"] <= DISTRIBUTION_BAND[1],
                    "detail": f"ticket médio do último lote {r['batch_id']}: R$ {r['avg_ticket']:,.2f} vs mediana "
                              f"R$ {r['med']:,.2f} ({r['ratio']:.1f}x)"})
    return out


def schema(con) -> list[dict]:
    out = []
    for c in contracts.load_all():
        s, t = c.physical.split(".")
        present = {r["column_name"] for r in rows(con, "SELECT column_name FROM information_schema.columns "
                                                     "WHERE table_schema=? AND table_name=?", [s, t])}
        expected = set(c.columns) | {"batch_id"}
        extra, missing = sorted(present - expected), sorted(expected - present)
        # coluna obrigatória que passou a chegar nula no último lote = renomeação upstream típica
        nulls = []
        for p in c.properties:
            if p.get("required") and p["name"] in present:
                n = con.execute(f"""SELECT COUNT(*) FILTER (WHERE {p['name']} IS NULL) / COUNT(*) FROM {c.physical}
                                    WHERE batch_id = (SELECT batch_id FROM {c.physical} ORDER BY ingested_at DESC LIMIT 1)
                                 """).fetchone()[0]
                if n and n > 0.5:
                    nulls.append(f"{p['name']} {n:.0%} nulo no último lote")
        ok = not (extra or missing or nulls)
        out.append({"pillar": "esquema", "target": c.physical, "ok": ok,
                    "detail": "conforme contrato v" + c.version if ok else
                    "; ".join(filter(None, [extra and f"colunas inesperadas {extra}",
                                            missing and f"colunas ausentes {missing}", *nulls]))})
    return out


def report(con) -> list[dict]:
    return freshness(con) + volume(con) + distribution(con) + schema(con)


def block_anomalous_batches(con) -> list[str]:
    """Ação corretiva do post-mortem: promover a checagem de distribuição a disjuntor."""
    bad = [r["batch_id"] for r in distribution_by_batch(con)
           if not DISTRIBUTION_BAND[0] <= r["ratio"] <= DISTRIBUTION_BAND[1]]
    for b in bad:
        con.execute("""INSERT INTO quarantine.conversions
            SELECT to_json(c), batch_id, ingested_at, ['anomalia de distribuição: ticket médio fora da banda'], now()
            FROM silver.conversions c WHERE batch_id = ?""", [b])
        con.execute("DELETE FROM silver.conversions WHERE batch_id = ?", [b])
        con.execute("UPDATE meta.batch_status SET status='barred' WHERE batch_id = ?", [b])
    return bad


# ------------------------------------------------------------------ linhagem

LINEAGE = {
    "feed:ga4 (site)": ["bronze.conversions"],
    "feed:meta_capi": ["bronze.conversions"],
    "feed:ads_api": ["bronze.ad_spend"],
    "bronze.conversions": ["contrato conversions", "silver.conversions"],
    "bronze.ad_spend": ["contrato ad_spend", "silver.ad_spend"],
    "silver.conversions": ["gold.campaign_daily", "gold.source_health"],
    "silver.ad_spend": ["gold.campaign_daily", "gold.source_health"],
    "gold.campaign_daily": ["métrica net_revenue", "métrica roas", "métrica cac", "métrica orders"],
    "gold.source_health": ["guarda de frescor (semântica)", "pré-condição dados_frescos"],
    "métrica roas": ["tool get_campaign_performance"],
    "métrica net_revenue": ["tool get_campaign_performance"],
    "métrica cac": ["tool get_campaign_performance"],
    "métrica orders": ["tool get_campaign_performance"],
    "guarda de frescor (semântica)": ["tool get_campaign_performance"],
    "pré-condição dados_frescos": ["tool adjust_campaign_budget"],
    "tool get_campaign_performance": ["agente de orçamento"],
    "tool adjust_campaign_budget": ["ops.campaigns (plataforma de anúncios)"],
    "agente de orçamento": ["tool adjust_campaign_budget"],
}


def downstream(node: str, seen: set | None = None) -> dict:
    seen = seen or set()
    if node in seen:
        return {}
    seen.add(node)
    return {child: downstream(child, seen) for child in LINEAGE.get(node, [])}


def decisions_since(con, ts) -> list[dict]:
    ts = datetime.fromisoformat(ts) if isinstance(ts, str) else ts
    return rows(con, """
        SELECT change_id AS id, campaign_id, action, old_value || ' -> ' || new_value AS change, trace_id,
               changed_at AS ts, 'executada' AS kind FROM ops.change_log WHERE changed_at >= ?
        UNION ALL
        SELECT request_id, json_extract_string(params, '$.campaign_id'), action, json_extract_string(params,
               '$.new_daily_budget_brl'), trace_id, requested_at, 'na fila' FROM ops.approval_queue
        WHERE requested_at >= ? ORDER BY ts""", [ts, ts])
