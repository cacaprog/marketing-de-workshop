"""Fase 4 — fontes simuladas da Aurora: o "mundo de fora" que a ingestão (dlt) consulta.

Quatro sistemas de origem sob prefixos: `/ads` (investimento), `/ga4` (conversões), `/meta` (Conversions API) e
`/catalogo` (campanhas). O estado deles é um DuckDB próprio (fontes.duckdb) escrito pelo GERADOR COMPARTILHADO,
sem cópia: `bronze.*` lá dentro = o que cada fonte já entregou (com o horário de entrega em `ingested_at`) e
`meta.upstream_backlog` = o que a Meta ainda segura. Incidentes do Bloco 5 acontecem AQUI (incidents.inject).

Um processo, duas apps (contracts/upstream-api.md):
- `public_app` (porta 8000, publicada só em 127.0.0.1): rotas das fontes e /docs;
- `admin_app` (porta 8001, nunca publicada): reset, backfill, incidentes, plano de falhas.

As falhas são roteirizadas e determinísticas por execução (cabeçalho `X-Execucao`): nada de aleatório.
"""
from __future__ import annotations

import asyncio
import os
import threading
from datetime import datetime

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from agentready import generate, incidents
from agentready_stack import ingestion

FONTES = ("ads", "ga4", "meta_capi", "catalogo")
ROTA = {"ads": "ads", "ga4": "ga4", "meta_capi": "meta", "catalogo": "catalogo"}   # nome do registro → prefixo
FALHAS = ("padrao", "nenhuma", "todas")
PAGE_SIZE_MAX = 5000

# fonte → (tabela no armazém, filtro, chave de ordenação estável)
_TABELA = {
    "ads": ("bronze.ad_spend", "TRUE"),
    "ga4": ("bronze.conversions", "source = 'ga4'"),
    "meta_capi": ("bronze.conversions", "source = 'meta_capi'"),
    "catalogo": ("bronze.campaigns", "TRUE"),
}

_lock = threading.RLock()
_planos: dict[str, tuple[str, str]] = {}          # execução → (falhas_upstream, fonte_fora_do_ar)
_tentativas: dict[tuple, int] = {}                # (execução, fonte, recurso, página) → nº de tentativas
_estado = {"cenario_gerado_em": None}
# O armazém das fontes. No container: AGENTREADY_DB=/opt/stack-data/upstream/fontes.duckdb (só este processo o abre).
STORE = {"path": os.environ.get("UPSTREAM_STORE_DB") or os.environ.get("AGENTREADY_DB",
                                                                       "/opt/stack-data/upstream/fontes.duckdb")}


def deve_falhar(plano: tuple[str, str], execucao: str | None, fonte: str, pagina: int, tentativa: int) -> bool:
    """Decisão pura de falha (contracts/upstream-api.md → "Failure plan").

    `pagina` 0 = o manifesto de lotes. `fonte` usa os nomes do registro de carga (meta_capi ↔ rota /meta)."""
    falhas, fora = plano
    if fora == fonte:
        return True                                   # a fonte está fora do ar a execução inteira
    if falhas == "todas":
        return tentativa == 1                         # a 1ª tentativa de TODA página falha uma vez
    if falhas == "padrao":
        return fonte == "ga4" and pagina == 2 and tentativa == 1
    return False


def _con():
    return ingestion.store_connect(STORE["path"])


def _generate(now: datetime | None = None) -> dict:
    return ingestion.store_generate(STORE["path"], now)


def _ensure_scenario() -> None:
    with _lock:
        con = _con()
        try:
            ok = con.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema='bronze' "
                             "AND table_name='conversions'").fetchone()[0]
        finally:
            con.close()
        if not ok:
            stats = _generate()
            _estado["cenario_gerado_em"] = stats["generated_at"]


def _columns(con, table: str) -> list[str]:
    schema, name = table.split(".")
    return [r[0] for r in con.execute("SELECT column_name FROM information_schema.columns WHERE table_schema=? "
                                      "AND table_name=? ORDER BY ordinal_position", [schema, name]).fetchall()]


def _serializa(row: dict) -> dict:
    """Valores exatamente como o gerador gravou (texto); o lote renomeado chega com utm_campaign e SEM campaign_id."""
    out = {}
    renomeado = row.get("utm_campaign") is not None
    for k, v in row.items():
        if k == "utm_campaign" and not renomeado:
            continue
        if k == "campaign_id" and renomeado:
            continue
        out[k] = v.isoformat() if isinstance(v, datetime) else v
    return out


def _falha_ou_none(request: Request, fonte: str, recurso: str, pagina: int) -> JSONResponse | None:
    execucao = request.headers.get("X-Execucao")
    with _lock:
        key = (execucao, fonte, recurso, pagina)
        _tentativas[key] = _tentativas.get(key, 0) + 1
        tentativa = _tentativas[key]
        plano = _planos.get(execucao or "", ("padrao", "nenhuma"))
    if deve_falhar(plano, execucao, fonte, pagina, tentativa):
        return JSONResponse({"erro": "indisponível temporariamente"}, status_code=503, headers={"Retry-After": "1"})
    return None


# ----------------------------------------------------------------------------------------------- app pública

public_app = FastAPI(
    title="Fontes da Aurora (simuladas)",
    description="As quatro fontes que a ingestão (dlt) consulta: investimento (ads), conversões do GA4, Conversions "
                "API da Meta e o catálogo de campanhas. Os dados vêm do gerador compartilhado do workshop; as falhas "
                "(503, Meta parada, lotes reenviados) são roteirizadas por execução, como na vida real — só que "
                "sempre iguais.",
    version="1.0.0")


@public_app.get("/saude", summary="Saúde da API pública")
def saude_publica() -> dict:
    return {"ok": True}


def _lotes(request: Request, fonte: str) -> JSONResponse | dict:
    falha = _falha_ou_none(request, fonte, "lotes", 0)
    if falha:
        return falha
    table, where = _TABELA[fonte]
    with _lock:
        con = _con()
        try:
            rows = con.execute(f"""SELECT batch_id, max(ingested_at) AS delivered_at, count(*) AS rows,
                                          CAST(bit_xor(hash(t)) AS VARCHAR) AS checksum
                                   FROM {table} t WHERE {where} GROUP BY batch_id ORDER BY delivered_at, batch_id"""
                               ).fetchall()
        finally:
            con.close()
    return {"fonte": fonte, "lotes": [{"batch_id": b, "delivered_at": d.isoformat() if d else None, "rows": n,
                                       "checksum": c} for b, d, n, c in rows]}


def _pagina(request: Request, fonte: str, page: int, page_size: int) -> JSONResponse | dict:
    if page < 1 or not 1 <= page_size <= PAGE_SIZE_MAX:
        raise HTTPException(422, f"page >= 1 e 1 <= page_size <= {PAGE_SIZE_MAX}")
    falha = _falha_ou_none(request, fonte, "dados", page)
    if falha:
        return falha
    table, where = _TABELA[fonte]
    with _lock:
        con = _con()
        try:
            cols = _columns(con, table)
            cur = con.execute(f"SELECT {', '.join(cols)} FROM {table} WHERE {where} ORDER BY ALL "
                              f"LIMIT {page_size + 1} OFFSET {(page - 1) * page_size}")
            data = [dict(zip(cols, r)) for r in cur.fetchall()]
        finally:
            con.close()
    more = len(data) > page_size
    return {"data": [_serializa(r) for r in data[:page_size]], "page": page, "next_page": page + 1 if more else None}


def _rotas(fonte: str, recurso: str, resumo: str) -> None:
    prefix = f"/{ROTA[fonte]}/v1"

    @public_app.get(f"{prefix}/lotes", summary=f"{resumo}: manifesto de lotes entregues", tags=[ROTA[fonte]],
                    name=f"lotes_{fonte}")
    def lotes(request: Request, x_execucao: str | None = Header(default=None)):
        return _lotes(request, fonte)

    @public_app.get(f"{prefix}/{recurso}", summary=f"{resumo}: linhas (paginadas)", tags=[ROTA[fonte]],
                    name=f"dados_{fonte}")
    def dados(request: Request, page: int = 1, page_size: int = 500, x_execucao: str | None = Header(default=None)):
        return _pagina(request, fonte, page, page_size)


_rotas("ads", "investimento", "Investimento em mídia por campanha e dia")
_rotas("ga4", "conversoes", "Conversões do GA4 (e-commerce)")
_rotas("meta_capi", "conversoes", "Conversões da Meta (Conversions API)")
_rotas("catalogo", "campanhas", "Catálogo de campanhas")


# ----------------------------------------------------------------------------------------------- app de admin

admin_app = FastAPI(title="Administração das fontes (rede interna)", docs_url=None, redoc_url=None, openapi_url=None)


def _erro(e: Exception) -> JSONResponse:
    return JSONResponse({"erro": str(e)}, status_code=409)


class Reset(BaseModel):
    now: datetime | None = None


class Incidente(BaseModel):
    tipo: str


class Falhas(BaseModel):
    execucao: str
    falhas_upstream: str = "padrao"
    fonte_fora_do_ar: str = "nenhuma"


@admin_app.get("/admin/saude")
def saude_admin() -> dict:
    return {"ok": True, "cenario_gerado_em": _estado["cenario_gerado_em"]}


@admin_app.post("/admin/cenario/reset")
def reset(body: Reset | None = None):
    with _lock:
        try:
            stats = _generate(body.now if body else None)
        except Exception as e:  # noqa: BLE001 — devolve 409 com a mensagem
            return _erro(e)
        _estado["cenario_gerado_em"] = stats["generated_at"]
        _tentativas.clear()
    return stats


@admin_app.post("/admin/meta/backfill")
def backfill():
    with _lock:
        con = _con()
        try:
            return {"linhas": generate.backfill_meta(con)}
        except Exception as e:  # noqa: BLE001
            return _erro(e)
        finally:
            con.close()


@admin_app.post("/admin/incidentes")
def injetar(body: Incidente):
    with _lock:
        con = _con()
        try:
            r = incidents.inject(con, None if body.tipo == "aleatorio" else body.tipo)
            has = con.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema='ops' "
                              "AND table_name='incidents'").fetchone()[0]
            row = con.execute("SELECT incident_id, kind, injected_at, detected_at, resolved_at, batch_id "
                              "FROM ops.incidents WHERE incident_id = ?", [r["incident_id"]]).fetchone() if has else None
            # Sem o registro (ex.: injeção simulada num teste): devolve o que a injeção informou.
            row = row or (r["incident_id"], body.tipo, r.get("injected_at") or datetime.now().isoformat(), None, None, None)
        except Exception as e:  # noqa: BLE001
            return _erro(e)
        finally:
            con.close()
    keys = ("incident_id", "kind", "injected_at", "detected_at", "resolved_at", "batch_id")
    return {k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in zip(keys, row)}


@admin_app.post("/admin/incidentes/resolver")
def resolver():
    with _lock:
        con = _con()
        try:
            m = incidents.resolve(con)
        except Exception as e:  # noqa: BLE001
            return _erro(e)
        finally:
            con.close()
    return {k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in m.items()}


@admin_app.put("/admin/falhas")
def falhas(body: Falhas):
    if body.falhas_upstream not in FALHAS:
        return _erro(ValueError(f"falhas_upstream inválido: {body.falhas_upstream}. Use {FALHAS}"))
    if body.fonte_fora_do_ar not in ("nenhuma", *FONTES):
        return _erro(ValueError(f"fonte_fora_do_ar inválida: {body.fonte_fora_do_ar}. Use {('nenhuma', *FONTES)}"))
    with _lock:
        _planos[body.execucao] = (body.falhas_upstream, body.fonte_fora_do_ar)
    return {"execucao": body.execucao, "falhas_upstream": body.falhas_upstream,
            "fonte_fora_do_ar": body.fonte_fora_do_ar}


# ----------------------------------------------------------------------------------------------- processo

async def _serve() -> None:
    import uvicorn
    host = os.environ.get("UPSTREAM_HOST", "0.0.0.0")
    servers = [uvicorn.Server(uvicorn.Config(app, host=host, port=port, log_level="warning"))
               for app, port in ((public_app, int(os.environ.get("UPSTREAM_PUBLIC_PORT", "8000"))),
                                 (admin_app, int(os.environ.get("UPSTREAM_ADMIN_PORT", "8001"))))]
    await asyncio.gather(*(s.serve() for s in servers))


def main() -> None:
    _ensure_scenario()
    asyncio.run(_serve())


if __name__ == "__main__":
    main()
