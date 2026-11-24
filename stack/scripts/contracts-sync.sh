#!/usr/bin/env bash
# Gera os testes dbt da Silver a partir dos contratos ODCS (datacontract-cli).
# Os arquivos são GERADOS e nunca versionados: a fonte única é contracts/*.odcs.yaml.
# Uso: contracts-sync.sh [dir_contratos] [dir_saida]
set -euo pipefail
CONTRACTS="${1:-/opt/agentready/contracts}"
OUT="${2:-/opt/airflow/dbt/aurora/models/silver}"
DCC="${DATACONTRACT_BIN:-/opt/venvs/dcc/bin/datacontract}"
rm -f "$OUT"/_contract__*.generated.yml
for c in "$CONTRACTS"/*.odcs.yaml; do
  name="$(basename "$c" .odcs.yaml)"
  "$DCC" lint "$c" >/dev/null || { echo "contrato inválido: $c (rode: datacontract lint $c)" >&2; exit 1; }
  "$DCC" export dbt-models "$c" --output "$OUT/_contract__${name}.generated.yml" >/dev/null
  echo "testes gerados: $OUT/_contract__${name}.generated.yml"
done
