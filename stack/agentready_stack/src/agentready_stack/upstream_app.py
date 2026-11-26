"""Fase 4 — fontes simuladas da Aurora (ads, ga4, Meta, catálogo).

Esqueleto do spike (T008): duas apps num processo — `public_app` (porta 8000: rotas das fontes e /docs) e
`admin_app` (porta 8001: administração, só na rede interna). As rotas das fontes chegam na T027.
"""
from __future__ import annotations

import asyncio
import os

from fastapi import FastAPI

public_app = FastAPI(title="Fontes da Aurora (simuladas)",
                     description="As quatro fontes que a ingestão (dlt) consulta. Os dados vêm do gerador "
                                 "compartilhado do workshop; as falhas são roteirizadas por execução.")
admin_app = FastAPI(title="Administração das fontes (rede interna)", docs_url=None, redoc_url=None)


@public_app.get("/saude", summary="Saúde da API pública")
def saude_publica() -> dict:
    return {"ok": True}


@admin_app.get("/admin/saude")
def saude_admin() -> dict:
    return {"ok": True, "cenario_gerado_em": None}


async def _serve() -> None:
    import uvicorn
    servers = [uvicorn.Server(uvicorn.Config(app, host=os.environ.get("UPSTREAM_HOST", "0.0.0.0"), port=port,
                                             log_level="warning"))
               for app, port in ((public_app, 8000), (admin_app, 8001))]
    await asyncio.gather(*(s.serve() for s in servers))


def main() -> None:
    asyncio.run(_serve())


if __name__ == "__main__":
    main()
