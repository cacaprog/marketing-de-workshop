"""Fase 4 — as fontes simuladas (contracts/upstream-api.md): o que servem, como falham, o que fica escondido."""
import pytest
from fastapi.testclient import TestClient

from agentready_stack import ingestion, upstream_app


@pytest.fixture
def apps(monkeypatch, tmp_path):
    """Armazém das fontes novo, gerado pelo gerador compartilhado; as duas apps sobre ele."""
    store = str(tmp_path / "fontes.duckdb")
    ingestion.store_generate(store)
    monkeypatch.setitem(upstream_app.STORE, "path", store)
    monkeypatch.setattr(upstream_app, "_planos", {})
    monkeypatch.setattr(upstream_app, "_tentativas", {})
    pub, adm = TestClient(upstream_app.public_app), TestClient(upstream_app.admin_app)
    pub.store = store
    return pub, adm


def _all(pub, prefix, recurso, execucao="t"):
    rows, page = [], 1
    while page:
        r = pub.get(f"{prefix}/{recurso}", params={"page": page, "page_size": 2000}, headers={"X-Execucao": execucao})
        if r.status_code == 503:
            continue
        body = r.json()
        assert set(body) == {"data", "page", "next_page"}
        rows += body["data"]
        page = body["next_page"]
    return rows


def test_manifests_and_meta_backfill(apps):
    pub, adm = apps
    for prefix in ("/ads", "/ga4", "/meta", "/catalogo"):
        r = pub.get(f"{prefix}/v1/lotes", headers={"X-Execucao": "m"})
        assert r.status_code == 200 and r.json()["lotes"], prefix
        assert set(r.json()["lotes"][0]) == {"batch_id", "delivered_at", "rows", "checksum"}
    meta = {b["batch_id"] for b in pub.get("/meta/v1/lotes", headers={"X-Execucao": "m"}).json()["lotes"]}
    assert adm.post("/admin/meta/backfill").json()["linhas"] > 0
    meta2 = {b["batch_id"] for b in pub.get("/meta/v1/lotes", headers={"X-Execucao": "m"}).json()["lotes"]}
    assert len(meta2 - meta) == 3, "a Meta segura 3 dias até o backfill"


def test_values_are_served_exactly_as_stored(apps):
    pub, _ = apps
    rows = _all(pub, "/ga4/v1", "conversoes")
    c = ingestion.store_connect(pub.store)
    try:
        n = c.execute("SELECT count(*) FROM bronze.conversions WHERE source='ga4'").fetchone()[0]
        comma = c.execute("SELECT order_value_brl FROM bronze.conversions WHERE source='ga4' AND order_value_brl LIKE '%,%' "
                          "LIMIT 1").fetchone()[0]
        neg = c.execute("SELECT order_value_brl FROM bronze.conversions WHERE source='ga4' AND order_value_brl LIKE '-%' "
                        "LIMIT 1").fetchone()[0]
    finally:
        c.close()
    assert len(rows) == n
    values = {r["order_value_brl"] for r in rows}
    assert comma in values and neg in values, "valores sujos chegam como texto, sem conserto"
    assert any(r["campaign_id"] is None for r in rows), "campaign_id nulo chega como null"
    assert all(isinstance(r["order_value_brl"], (str, type(None))) for r in rows)
    assert _all(pub, "/ga4/v1", "conversoes") == rows, "ordem estável entre chamadas"


def test_renamed_batch_has_utm_campaign_and_no_campaign_id(apps):
    pub, adm = apps
    inc = adm.post("/admin/incidentes", json={"tipo": "renomeacao"}).json()
    assert inc["kind"] == "renomeacao" and inc["incident_id"].startswith("INC-")
    rows = _all(pub, "/ga4/v1", "conversoes")
    renamed = [r for r in rows if r["batch_id"].endswith("-redelivery")]
    # O lote renomeado: quem tem utm_campaign chega sem campaign_id; as poucas linhas sujas que já não tinham
    # campanha (as duas colunas nulas no armazém) chegam com campaign_id nulo — na Bronze, as duas colunas ficam nulas.
    assert renamed and not any(r.get("campaign_id") for r in renamed)
    assert all("campaign_id" not in r for r in renamed if "utm_campaign" in r)
    assert sum("utm_campaign" in r for r in renamed) > 0.9 * len(renamed)
    assert all("utm_campaign" not in r for r in rows if not r["batch_id"].endswith("-redelivery"))
    second = adm.post("/admin/incidentes", json={"tipo": "centavos"})
    assert second.status_code == 409 and "incidente aberto" in second.json()["erro"]


def test_failure_plan_is_deterministic():
    f = upstream_app.deve_falhar
    padrao, todas = ("padrao", "nenhuma"), ("todas", "nenhuma")
    assert f(padrao, "r", "ga4", 2, 1) and not f(padrao, "r", "ga4", 2, 2)
    assert not any(f(padrao, "r", s, p, 1) for s in ("ads", "meta_capi", "catalogo") for p in (0, 1, 2, 3))
    assert not f(padrao, "r", "ga4", 1, 1) and not f(padrao, "r", "ga4", 3, 1)
    assert all(f(todas, "r", s, p, 1) and not f(todas, "r", s, p, 2) for s in upstream_app.FONTES for p in (0, 1, 5))
    assert all(f(("nenhuma", "meta_capi"), "r", "meta_capi", p, t) for p in (0, 1, 9) for t in (1, 2, 4))
    assert upstream_app.ROTA["meta_capi"] == "meta"


def test_503_carries_retry_after_and_ptbr_body(apps):
    pub, adm = apps
    assert adm.put("/admin/falhas", json={"execucao": "x", "falhas_upstream": "padrao",
                                          "fonte_fora_do_ar": "meta_capi"}).status_code == 200
    r = pub.get("/ga4/v1/conversoes", params={"page": 2}, headers={"X-Execucao": "x"})
    assert r.status_code == 503 and r.headers["Retry-After"] == "1" and r.json() == {"erro": "indisponível temporariamente"}
    assert pub.get("/ga4/v1/conversoes", params={"page": 2}, headers={"X-Execucao": "x"}).status_code == 200
    assert pub.get("/meta/v1/lotes", headers={"X-Execucao": "x"}).status_code == 503
    assert adm.put("/admin/falhas", json={"execucao": "y", "falhas_upstream": "quase"}).status_code == 409


def test_admin_routes_are_not_on_the_public_app(apps):
    pub, adm = apps
    assert pub.get("/admin/saude").status_code == 404
    assert pub.post("/admin/cenario/reset").status_code in (404, 405)
    assert not [p for p in pub.get("/openapi.json").json()["paths"] if p.startswith("/admin")]
    assert adm.get("/admin/saude").json()["ok"] is True
    assert pub.get("/saude").json() == {"ok": True}
