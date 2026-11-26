# Contract: `upstream` — mock source systems

Service `upstream`, FastAPI on uvicorn. It runs from the stack image's agent venv with
`AGENTREADY_DB=/opt/stack-data/upstream/fontes.duckdb`. One process (`python -m agentready_stack.upstream_app`) serves
**two apps** that share one store connection and its lock, so the process is the single writer of `fontes.duckdb`:

| App | Port | Published | Serves |
|---|---|---|---|
| public | 8000 | only as `127.0.0.1:${UPSTREAM_PORT:-8000}` (never `0.0.0.0`, FR-020) | the source routes and `/docs`. Internal URL `UPSTREAM_URL=http://upstream:8000` |
| admin | 8001 | **never** (compose network only) | the admin routes. Internal URL `UPSTREAM_ADMIN_URL=http://upstream:8001` |

`/admin/*` doesn't exist on the public app (404).

## Source routes (what dlt reads)

Every source route takes an optional header, `X-Execucao: <dag_run_id>`, which keys the failure plan. All field
values are **strings exactly as stored by the generator** (`"210.50"`, `"1,5"`, `"-30.00"`, `null`).

| Route | Returns |
|---|---|
| `GET /{fonte}/v1/lotes` | `{"fonte", "lotes": [{"batch_id", "delivered_at", "rows", "checksum"}]}`, ordered by `delivered_at`. Meta's held days are **absent** until backfill |
| `GET /ads/v1/investimento?page=N&page_size=500` | rows of `ad_spend`: `spend_date, campaign_id, impressions, clicks, spend_brl, batch_id, ingested_at` |
| `GET /ga4/v1/conversoes?page=N&page_size=500` | `conversions` rows where `source='ga4'` |
| `GET /meta/v1/conversoes?page=N&page_size=500` | `conversions` rows where `source='meta_capi'` |
| `GET /catalogo/v1/campanhas?page=N&page_size=500` | `campaigns` rows |

Pagination: `{"data": [...], "page": N, "next_page": N+1 | null}`, with stable order (`batch_id`, then the row key).
A row whose source record has `utm_campaign` set (the `renomeacao` batch) is served **with `utm_campaign` and
without `campaign_id`**. Other rows never carry `utm_campaign`.

`fonte` path values: `ads`, `ga4`, `meta`, `catalogo`. The load record uses `ads`, `ga4`, `meta_capi`, `catalogo`.

## Failure plan

Source names: the failure plan uses the load-record names (`ads`, `ga4`, `meta_capi`, `catalogo`). `meta_capi` maps to the
route prefix `/meta`.

Tests may replace the decision function (`deve_falhar`) by monkeypatching. No test-only mode is served.

| Plan | Behavior |
|---|---|
| `falhas_upstream=padrao` (default) | the **first** request for `ga4` page 2 under a given `X-Execucao` answers `503` with `Retry-After: 1` and the body `{"erro": "indisponível temporariamente"}`. The retry succeeds |
| `falhas_upstream=todas` | the first request for **every** page of every source under a run id answers 503 once (SC-003) |
| `falhas_upstream=nenhuma` | never fails |
| `fonte_fora_do_ar=<fonte>` | every request to that source in that run answers 503 (exhausts retries, so the load is `falhou`) |

Determinism: the decision is a pure function of (plan, run id, route, page, attempt number). There is no randomness.

## Admin routes (admin app, port 8001, internal network only)

| Route | Effect | Shared code called |
|---|---|---|
| `POST /admin/cenario/reset` `{"now": iso?}` | regenerates the sources store | `generate.generate(now)` |
| `POST /admin/meta/backfill` | Meta delivers its held days (new batches, `delivered_at` = now) | `generate.backfill_meta(con)` |
| `POST /admin/incidentes` `{"tipo": kind \| "aleatorio"}` | changes yesterday's ga4 batch at the source | `incidents.inject(con, kind)` → returns the `ops.incidents` row |
| `POST /admin/incidentes/resolver` | the source restores the original batch | `incidents.resolve(con)` |
| `PUT /admin/falhas` `{"execucao", "falhas_upstream", "fonte_fora_do_ar"}` | sets the plan for one run id | — |
| `GET /admin/saude` | `{"ok": true, "cenario_gerado_em"}` (compose healthcheck on `:8001`) | — |

Errors: 409 with a pt-BR `{"erro": …}` when the shared code raises (for example, "já existe um incidente aberto").

## Guarantees

- The service never writes the lake or `ops.duckdb`.
- For the same scenario and reference time, the union of everything served equals the default track's Bronze
  (checked by parity's `bronze` section).
