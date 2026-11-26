"""Gera o cenário sintético da 'Aurora Cosméticos' na camada Bronze.

O cenário é determinístico (seed fixa) e ancorado no horário atual, para que os
SLAs de frescor façam sentido em qualquer dia em que o workshop for apresentado.

Problemas plantados de propósito (o "fio condutor" do workshop):
  1. Feed meta_capi parado há 3 dias  -> campanhas Meta parecem ter vendido ZERO.
  2. Lote do ga4 de anteontem carregado duas vezes (retry sem idempotência).
  3. ~1% de linhas sujas espalhadas (valor negativo, vírgula decimal, campanha inexistente).
  4. Um lote antigo do ga4 com bug upstream (40% de valores negativos) -> deve ser barrado inteiro.
"""
from __future__ import annotations

import csv
import os
import random
import tempfile
from datetime import datetime, timedelta

from agentready.db import SCHEMAS, connect

SEED = 42
DAYS = 30
STALLED_META_DAYS = 3        # meta_capi não entrega há 3 dias
DUPLICATED_GA4_DAY = 2       # lote de "anteontem" do ga4 carregado em dobro
BROKEN_GA4_DAY = 20          # lote antigo com bug upstream

CAMPAIGNS = [
    # id,  nome,                            canal,           objetivo,     orçamento, ROAS líquido real, ticket médio
    ("C01", "Google Search - Marca",        "google_search", "conversion", 4000, 7.5, 210.0),
    ("C02", "Google Search - Genérico",     "google_search", "conversion", 5000, 2.8, 190.0),
    ("C03", "Meta - Prospecção",            "meta",          "conversion", 6000, 4.2, 230.0),
    ("C04", "Meta - Remarketing",           "meta",          "conversion", 3000, 6.0, 250.0),
    ("C05", "TikTok - Awareness",           "tiktok",        "awareness",  2500, 0.6, 160.0),
    ("C06", "YouTube - Vídeo Conversão",    "youtube",       "conversion", 3500, 0.85, 200.0),
]
OWNERS = {"google_search": "ana.search", "meta": "bruno.social", "tiktok": "carla.brand", "youtube": "carla.brand"}
DISCOUNT_RATE = 0.10


def source_for(channel: str) -> str:
    return "meta_capi" if channel == "meta" else "ga4"


def _reset(con) -> None:
    for s in SCHEMAS:
        con.execute(f"DROP SCHEMA IF EXISTS {s} CASCADE")
        con.execute(f"CREATE SCHEMA {s}")
    con.execute("""
        CREATE TABLE bronze.campaigns (campaign_id VARCHAR, campaign_name VARCHAR, channel VARCHAR,
            objective VARCHAR, owner VARCHAR, batch_id VARCHAR, ingested_at TIMESTAMP)""")
    con.execute("""
        CREATE TABLE bronze.ad_spend (spend_date VARCHAR, campaign_id VARCHAR, impressions VARCHAR,
            clicks VARCHAR, spend_brl VARCHAR, batch_id VARCHAR, ingested_at TIMESTAMP)""")
    con.execute("""
        CREATE TABLE bronze.conversions (conversion_id VARCHAR, campaign_id VARCHAR, source VARCHAR,
            order_value_brl VARCHAR, discount_brl VARCHAR, converted_at VARCHAR,
            batch_id VARCHAR, ingested_at TIMESTAMP)""")
    create_ops_tables(con)


def create_ops_tables(con) -> None:
    """Estado "vivo" da plataforma de anúncios (o que o agente lê e altera).

    Separado de `_reset` para a trilha stack criar as MESMAS tabelas no ops.duckdb (Fase 4), sem copiar o DDL."""
    con.execute("""
        CREATE TABLE ops.campaigns (campaign_id VARCHAR PRIMARY KEY, daily_budget_brl DOUBLE,
            status VARCHAR, locked_by_human BOOLEAN, updated_at TIMESTAMP)""")
    con.execute("""
        CREATE TABLE ops.change_log (change_id VARCHAR, campaign_id VARCHAR, action VARCHAR,
            field VARCHAR, old_value VARCHAR, new_value VARCHAR, actor VARCHAR, trace_id VARCHAR,
            justification VARCHAR, changed_at TIMESTAMP, rolled_back BOOLEAN DEFAULT FALSE)""")
    con.execute("""
        CREATE TABLE ops.approval_queue (request_id VARCHAR, action VARCHAR, params JSON, reason VARCHAR,
            requested_by VARCHAR, trace_id VARCHAR, status VARCHAR, requested_at TIMESTAMP,
            decided_by VARCHAR, decided_at TIMESTAMP)""")


def seed_live_state(con, now: datetime) -> None:
    """Orçamentos e status iniciais das campanhas (o mesmo ponto de partida em todas as trilhas)."""
    con.executemany(
        "INSERT INTO ops.campaigns VALUES (?,?,?,?,?)",
        [(c[0], float(c[4]), "active", False, now - timedelta(days=7)) for c in CAMPAIGNS],
    )


def _bulk_insert(con, table: str, data: list[tuple]) -> None:
    """COPY a partir de CSV temporário: ordens de grandeza mais rápido que executemany."""
    with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, newline="", encoding="utf-8") as f:
        csv.writer(f).writerows(data)
    try:
        con.execute(f"COPY {table} FROM '{f.name}' (HEADER false)")
    finally:
        os.unlink(f.name)


def generate(now: datetime | None = None) -> dict:
    rng = random.Random(SEED)
    now = (now or datetime.now()).replace(microsecond=0)
    today = now.date()
    con = connect()
    _reset(con)

    con.executemany(
        "INSERT INTO bronze.campaigns VALUES (?,?,?,?,?,?,?)",
        [(c[0], c[1], c[2], c[3], OWNERS[c[2]], "campaigns-seed", now - timedelta(days=1)) for c in CAMPAIGNS],
    )
    seed_live_state(con, now)

    spend_rows, conv_rows, held = [], [], []
    seq = 0
    for k in range(DAYS, 0, -1):                       # k = dias atrás (1 = ontem)
        day = today - timedelta(days=k)
        ingested = now - timedelta(hours=24 * (k - 1) + 3)
        day_conv: dict[str, list] = {"ga4": [], "meta_capi": []}
        for cid, _name, channel, _obj, budget, roas, aov in CAMPAIGNS:
            spend = round(budget * rng.uniform(0.90, 1.0), 2)
            impressions = int(spend * rng.uniform(80, 140))
            clicks = int(impressions * rng.uniform(0.008, 0.03))
            spend_rows.append((day.isoformat(), cid, str(impressions), str(clicks), f"{spend:.2f}",
                               f"ads_api-{day}", ingested))
            # receita líquida alvo = spend * ROAS * ruído; bruto = líquido / (1 - desconto)
            net_target = spend * roas * rng.uniform(0.85, 1.15)
            n = max(1, round(net_target / (aov * (1 - DISCOUNT_RATE))))
            for _ in range(n):
                seq += 1
                gross = round(rng.gauss(aov, aov * 0.25), 2)
                gross = max(gross, 39.9)
                disc = round(gross * rng.uniform(0.0, 2 * DISCOUNT_RATE), 2)
                ts = datetime.combine(day, datetime.min.time()) + timedelta(seconds=rng.randint(0, 86399))
                day_conv[source_for(channel)].append(
                    [f"ORD-{seq:07d}", cid, source_for(channel), f"{gross:.2f}", f"{disc:.2f}", ts.isoformat()])

        for source, rows_ in day_conv.items():
            if source == "meta_capi" and k <= STALLED_META_DAYS:
                held += [(*r, f"{source}-{day}") for r in rows_]   # problema 1: feed parado
                continue
            if source == "ga4" and k == BROKEN_GA4_DAY:        # problema 4: bug upstream no lote
                for r in rows_:
                    if rng.random() < 0.40:
                        r[3] = f"-{r[3]}"
            for r in rows_:                                    # problema 3: sujeira esparsa (~1%)
                roll = rng.random()
                if roll < 0.003:
                    r[3] = f"-{r[3]}"
                elif roll < 0.006:
                    r[3] = r[3].replace(".", ",")
                elif roll < 0.008:
                    r[1] = "C99"
                elif roll < 0.010:
                    r[1] = None
            batch = f"{source}-{day}"
            conv_rows += [(*r, batch, ingested) for r in rows_]
            if source == "ga4" and k == DUPLICATED_GA4_DAY:    # problema 2: retry duplicou o lote
                conv_rows += [(*r, batch + "-retry", ingested + timedelta(minutes=40)) for r in rows_]

    _bulk_insert(con, "bronze.ad_spend", spend_rows)
    _bulk_insert(con, "bronze.conversions", conv_rows)
    # O que a Meta ainda vai entregar quando a integração for corrigida (ver backfill_meta).
    con.execute("CREATE TABLE meta.upstream_backlog AS SELECT * EXCLUDE (ingested_at) FROM bronze.conversions WHERE false")
    _bulk_insert(con, "meta.upstream_backlog", held)
    stats = {
        "ad_spend_rows": len(spend_rows),
        "conversion_rows": len(conv_rows),
        "generated_at": now.isoformat(),
    }
    con.close()
    return stats


def backfill_meta(con) -> int:
    """O time de dados corrigiu o token da Conversions API: os lotes atrasados chegam agora."""
    n = con.execute("SELECT COUNT(*) FROM meta.upstream_backlog").fetchone()[0]
    con.execute("INSERT INTO bronze.conversions SELECT *, now()::TIMESTAMP FROM meta.upstream_backlog")
    con.execute("DELETE FROM meta.upstream_backlog")
    return n
