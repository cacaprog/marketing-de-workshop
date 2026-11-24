"""Validação de contratos ODCS: Bronze -> Silver (válidos) + Quarentena (dead-letter).

O contrato é a lei: cada regra do YAML vira um predicado SQL. Linhas que violam
qualquer regra vão para a quarentena com o motivo. Se a taxa de quarentena de um
lote passar do limite do contrato, o disjuntor barra o LOTE INTEIRO.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from agentready.settings import CONTRACTS_DIR, load_yaml

CASTS = {"number": "DOUBLE", "integer": "BIGINT", "date": "DATE", "timestamp": "TIMESTAMP"}


@dataclass
class Contract:
    name: str
    version: str
    table: str
    physical: str
    properties: list[dict]
    sla: dict[str, dict]
    raw: dict

    @property
    def columns(self) -> list[str]:
        return [p["name"] for p in self.properties]

    @property
    def primary_key(self) -> list[str]:
        pk = [p for p in self.properties if p.get("primaryKey")]
        return [p["name"] for p in sorted(pk, key=lambda p: p.get("primaryKeyPosition", 0))]

    @property
    def freshness_hours(self) -> float | None:
        s = self.sla.get("latency")
        return float(s["value"]) if s else None

    @property
    def freshness_partition(self) -> str | None:
        """Coluna que separa o SLA de frescor por feed. No ODCS fica em customProperties do schema
        (o SLA não tem campo de partição); `partitionBy` no SLA é aceito por compatibilidade."""
        for cp in self.raw["schema"][0].get("customProperties") or []:
            if cp.get("property") == "freshnessPartitionBy":
                return cp.get("value")
        return (self.sla.get("latency") or {}).get("partitionBy")

    @property
    def max_quarantine_rate(self) -> float:
        return float((self.sla.get("maxQuarantineRate") or {}).get("value", 1.0))


def load(name: str, path: Path | None = None) -> Contract:
    raw = load_yaml(path or CONTRACTS_DIR / f"{name}.odcs.yaml")
    obj = raw["schema"][0]
    return Contract(
        name=raw["name"], version=raw["version"], table=obj["name"], physical=obj["physicalName"],
        properties=obj["properties"], sla={s["property"]: s for s in raw.get("slaProperties", [])}, raw=raw,
    )


def load_all() -> list[Contract]:
    return [load(p.name.removesuffix(".odcs.yaml")) for p in sorted(CONTRACTS_DIR.glob("*.odcs.yaml"))]


def _q(v: str) -> str:
    return "'" + str(v).replace("'", "''") + "'"


def violation_exprs(c: Contract) -> list[str]:
    """Traduz as regras do contrato em expressões SQL que devolvem o motivo ou NULL."""
    exprs = []
    for p in c.properties:
        col, typ = p["name"], p.get("logicalType", "string")
        if p.get("required"):
            exprs.append(f"CASE WHEN {col} IS NULL THEN '{col}: obrigatório ausente' END")
        if typ in CASTS and col != "ingested_at":
            exprs.append(f"CASE WHEN {col} IS NOT NULL AND TRY_CAST({col} AS {CASTS[typ]}) IS NULL "
                         f"THEN '{col}: tipo inválido (esperado {typ}) valor=' || {col} END")
        opts = p.get("logicalTypeOptions") or {}
        if "minimum" in opts:
            exprs.append(f"CASE WHEN TRY_CAST({col} AS DOUBLE) < {opts['minimum']} "
                         f"THEN '{col}: abaixo do mínimo {opts['minimum']} valor=' || {col} END")
        if "maximum" in opts:
            exprs.append(f"CASE WHEN TRY_CAST({col} AS DOUBLE) > {opts['maximum']} "
                         f"THEN '{col}: acima do máximo {opts['maximum']} valor=' || {col} END")
        for rule in p.get("quality") or []:
            # ODCS 3.1: `metric: invalidValues` + `arguments.validValues`; `rule: validValues` é a forma antiga.
            valid = ((rule.get("arguments") or {}).get("validValues") if rule.get("metric") == "invalidValues"
                     else rule.get("validValues") if rule.get("rule") == "validValues" else None)
            if valid:
                values = ", ".join(_q(v) for v in valid)
                exprs.append(f"CASE WHEN {col} IS NOT NULL AND {col} NOT IN ({values}) "
                             f"THEN '{col}: valor fora do domínio ' || {col} END")
    keys = [p["name"] for p in c.properties if p.get("unique")] or []
    key_sets = [[k] for k in keys]
    if len(c.primary_key) > 1:
        key_sets.append(c.primary_key)
    for ks in key_sets:
        part = ", ".join(ks)
        exprs.append(f"CASE WHEN ROW_NUMBER() OVER (PARTITION BY {part} ORDER BY ingested_at, batch_id) > 1 "
                     f"THEN 'duplicado: ({part}) já carregado' END")
    return exprs


def missing_columns(con, c: Contract) -> list[str]:
    schema, table = c.physical.split(".")
    present = {r[0] for r in con.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_schema=? AND table_name=?",
        [schema, table]).fetchall()}
    return [col for col in c.columns if col not in present]


def apply(con, c: Contract) -> dict:
    """Valida a tabela Bronze do contrato e materializa silver.<t>, quarantine.<t> e meta.batch_status."""
    t = c.table
    missing = missing_columns(con, c)
    if missing:
        # Quebra de esquema: nada pode ser interpretado. A Silver mantém o último estado
        # bom (não é sobrescrita) e o SLA de frescor vai acusar o atraso.
        _record_batches(con, c, schema_break=True)
        return {"contract": c.name, "version": c.version, "schema_violation": missing}

    viol = ", ".join(violation_exprs(c))
    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE _checked AS
        SELECT b.*, list_filter([{viol}], lambda x: x IS NOT NULL) AS violations FROM {c.physical} b""")
    con.execute("""
        CREATE OR REPLACE TEMP TABLE _batch AS
        SELECT batch_id, COUNT(*) AS n, COUNT(*) FILTER (WHERE len(violations) > 0) AS bad,
               bad / n AS rate FROM _checked GROUP BY batch_id""")
    limit = c.max_quarantine_rate
    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE _final AS
        SELECT k.* REPLACE (
            CASE WHEN bt.rate > {limit} AND len(k.violations) = 0
                 THEN ['lote barrado pelo disjuntor: ' || round(bt.rate * 100, 1) || '% de quarentena > {limit * 100:.0f}%']
                 ELSE k.violations END AS violations)
        FROM _checked k JOIN _batch bt USING (batch_id)""")

    casts = ", ".join(
        f"CAST({p['name']} AS {CASTS[p.get('logicalType', 'string')]}) AS {p['name']}"
        if p.get("logicalType") in CASTS and p["name"] != "ingested_at" else p["name"]
        for p in c.properties)
    con.execute(f"CREATE OR REPLACE TABLE silver.{t} AS SELECT {casts}, batch_id FROM _final WHERE len(violations) = 0")
    payload = ", ".join(f"{col} := {col}" for col in c.columns)
    con.execute(f"""CREATE OR REPLACE TABLE quarantine.{t} AS
        SELECT to_json(struct_pack({payload})) AS payload, batch_id, ingested_at, violations,
               now() AS quarantined_at
        FROM _final WHERE len(violations) > 0""")
    _record_batches(con, c)
    n_ok = con.execute(f"SELECT COUNT(*) FROM silver.{t}").fetchone()[0]
    n_bad = con.execute(f"SELECT COUNT(*) FROM quarantine.{t}").fetchone()[0]
    barred = con.execute(f"SELECT COUNT(*) FROM _batch WHERE rate > {limit}").fetchone()[0]
    return {"contract": c.name, "version": c.version, "valid": n_ok, "quarantined": n_bad, "barred_batches": barred}


def _record_batches(con, c: Contract, schema_break: bool = False) -> None:
    con.execute("""CREATE TABLE IF NOT EXISTS meta.batch_status (contract VARCHAR, contract_version VARCHAR,
        batch_id VARCHAR, ingested_at TIMESTAMP, rows BIGINT, quarantined BIGINT, rate DOUBLE, status VARCHAR)""")
    con.execute("DELETE FROM meta.batch_status WHERE contract = ?", [c.name])
    if schema_break:
        con.execute(f"""INSERT INTO meta.batch_status SELECT ?, ?, batch_id, max(ingested_at), COUNT(*), COUNT(*), 1.0,
            'barred' FROM {c.physical} GROUP BY batch_id""", [c.name, c.version])
        return
    con.execute(f"""INSERT INTO meta.batch_status
        SELECT ?, ?, k.batch_id, max(k.ingested_at), bt.n, bt.bad, bt.rate,
               CASE WHEN bt.rate > {c.max_quarantine_rate} THEN 'barred' ELSE 'passed' END
        FROM _checked k JOIN _batch bt USING (batch_id) GROUP BY k.batch_id, bt.n, bt.bad, bt.rate""",
                [c.name, c.version])
