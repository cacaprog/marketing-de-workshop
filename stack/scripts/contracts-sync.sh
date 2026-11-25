#!/usr/bin/env bash
# Gera os testes dbt da Silver a partir dos contratos ODCS (datacontract-cli).
# Os arquivos são GERADOS e nunca versionados: a fonte única é contracts/*.odcs.yaml.
# Uso: contracts-sync.sh [dir_contratos] [dir_saida]
set -euo pipefail
CONTRACTS="${1:-/opt/agentready/contracts}"
OUT="${2:-/opt/airflow/dbt/aurora/models/silver}"
DCC="${DATACONTRACT_BIN:-/opt/venvs/dcc/bin/datacontract}"
# Gera numa pasta temporária e só troca o arquivo se o conteúdo mudou (troca atômica). Antes, apagar e
# regerar no lugar abria uma janela em que o Airflow relia o DAG SEM os testes do contrato, e a execução
# corrente perdia tarefas de teste (Fase 2, achado do `make test-live`).
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
for c in "$CONTRACTS"/*.odcs.yaml; do
  name="$(basename "$c" .odcs.yaml)"
  "$DCC" lint "$c" >/dev/null || { echo "contrato inválido: $c (rode: datacontract lint $c)" >&2; exit 1; }
  "$DCC" export dbt-models "$c" --output "$TMP/_contract__${name}.generated.yml" >/dev/null
done
for f in "$TMP"/_contract__*.generated.yml; do
  dest="$OUT/$(basename "$f")"
  if ! cmp -s "$f" "$dest"; then cp "$f" "$dest.tmp" && mv -f "$dest.tmp" "$dest"; echo "testes gerados: $dest"
  else echo "testes sem mudança: $dest"; fi
done
for dest in "$OUT"/_contract__*.generated.yml; do             # contrato removido: remove os testes dele
  [ -e "$dest" ] && [ ! -e "$TMP/$(basename "$dest")" ] && rm -f "$dest" && echo "testes removidos: $dest"
done

# Fase 2 — Elementary: cria/atualiza as tabelas do Elementary no warehouse e envia os artefatos do projeto
# UMA vez aqui (o upload automático por invocação está desligado: o Cosmos roda uma invocação por tarefa;
# pesquisa R6). Pule com STACK_SKIP_ELEMENTARY_SETUP=1.
if [ "${STACK_SKIP_ELEMENTARY_SETUP:-0}" != "1" ]; then
  DBT="${STACK_DBT_BIN:-/opt/venvs/dbt/bin/dbt}"
  PROJ="$(cd "$OUT/../.." && pwd)"
  TARGET="${DBT_TARGET_PATH:-/tmp/dbt_target_sync}"
  "$DBT" run --select package:elementary --project-dir "$PROJ" --profiles-dir "$PROJ" \
      --target-path "$TARGET" --quiet \
    || { echo "Elementary: não consegui criar as tabelas do Elementary (veja a saída acima)" >&2; exit 1; }
  "$DBT" run-operation elementary.upload_dbt_artifacts --project-dir "$PROJ" --profiles-dir "$PROJ" \
      --target-path "$TARGET" --quiet \
    || { echo "Elementary: não consegui enviar os artefatos do projeto" >&2; exit 1; }
  echo "Elementary: tabelas e artefatos do projeto atualizados"
fi
