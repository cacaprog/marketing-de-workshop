# Trilha stack — comandos. Rode a partir de stack/.  `make help` lista tudo.
SHELL := /bin/bash
-include .env            # mesmas variáveis que o docker compose lê (AIRFLOW_PORT, TZ, ...)
export AIRFLOW_UID ?= $(shell id -u)
COMPOSE := docker compose
# O entrypoint oficial só executa direto comandos 'bash'/'python'; o resto vira 'airflow ...'.
RUN := $(COMPOSE) run --rm --no-deps airflow-scheduler bash -c
AGENT := /opt/venvs/agent/bin
AIRFLOW_PORT ?= 8080
MARQUEZ_WEB_PORT ?= 3000
REPORT_PORT ?= 8090
PHOENIX_PORT ?= 6006
UPSTREAM_PORT ?= 8000
API := http://localhost:$(AIRFLOW_PORT)
SCENARIO ?= todos
ARGS ?= {}
SVC ?= airflow-scheduler

.PHONY: help check up down reset logs test run approvals parity contracts-sync doctor rollback incidente observe test-live decisoes traces auditoria fontes snapshots consultar-em gold-em restaurar politica politica-testes

help:  ## lista os comandos
	@grep -hE '^[a-z-]+:.*## ' Makefile | sed 's/:.*## /\t/' | column -t -s $$'\t'

check:  ## confere Docker Compose >= 2.14, >= 4 CPUs e >= 8 GB de RAM livre
	@v=$$($(COMPOSE) version --short 2>/dev/null) || { echo "ERRO: 'docker compose' não encontrado. Instale o plugin Compose v2 (ex.: sudo apt install docker-compose-v2)."; exit 1; }; \
	 if [ "$$(printf '%s\n' 2.14.0 "$$v" | sort -V | head -1)" != "2.14.0" ]; then echo "ERRO: Docker Compose $$v é antigo; precisa >= 2.14."; exit 1; fi; \
	 cpus=$$(nproc); [ "$$cpus" -ge 4 ] || { echo "ERRO: só $$cpus CPUs; a trilha stack precisa de pelo menos 4."; exit 1; }; \
	 mem=$$(awk '/MemAvailable/ {print int($$2/1024/1024)}' /proc/meminfo 2>/dev/null || echo 99); \
	 [ "$$mem" -ge 8 ] || { echo "ERRO: só $${mem} GB de RAM livre; a trilha stack precisa de pelo menos 8 GB."; exit 1; }; \
	 echo "ok: Compose $$v, $$cpus CPUs, $${mem} GB livres"

config/passwords.json:
	@cp config/passwords.example.json config/passwords.json && echo "criado config/passwords.json (usuários de estudo local)"

# .env com o SEU UID: assim até um `docker compose ...` direto roda com o dono certo dos arquivos.
.env:
	@sed "s/^AIRFLOW_UID=.*/AIRFLOW_UID=$$(id -u)/" .env.example > .env && echo "criado stack/.env (AIRFLOW_UID=$$(id -u))"

up: check .env config/passwords.json  ## sobe a stack e espera ficar saudável
	@mkdir -p data data/otel-queue data/lake data/upstream
	$(COMPOSE) up -d --build --wait --remove-orphans
	@$(RUN) '$(AGENT)/agentready-stack doctor'
	@echo; echo "Stack no ar:"; \
	 echo "  Airflow (DAG, aprovações) ..... $(API)"; \
	 echo "  Linhagem (Marquez) ............ http://localhost:$(MARQUEZ_WEB_PORT)"; \
	 echo "  Relatório de observabilidade .. http://localhost:$(REPORT_PORT)"; \
	 echo "  Traces (Phoenix) .............. http://localhost:$(PHOENIX_PORT)"; \
	 echo "  Fontes simuladas (APIs) ....... http://localhost:$(UPSTREAM_PORT)/docs"; \
	 echo "Usuários (só para estudo local): instrutor/instrutor (dispara execuções) · aprovadora/aprovadora (aprova ações)"

down:  ## para os serviços e mantém os dados
	$(COMPOSE) down

reset:  ## para tudo e APAGA os dados da trilha stack (camadas do lake (DuckLake), ops.duckdb, fontes simuladas, traces, Postgres, linhagem, relatório, Phoenix)
	$(COMPOSE) down -v
	@docker run --rm -v "$(CURDIR)/data:/d" alpine sh -c 'rm -rf /d/* /d/.[!.]* 2>/dev/null; true'
	@echo "dados da trilha stack apagados: camadas do lake (DuckLake: arquivos em data/lake e o catálogo no Postgres), ops.duckdb, fontes simuladas, log de auditoria, histórico de linhagem (Marquez), relatório, traces (Phoenix) e a fila do coletor (a trilha padrão em ../data não foi tocada)"

logs:  ## acompanha os logs de um serviço (SVC=airflow-scheduler)
	$(COMPOSE) logs -f $(SVC)

test:  ## roda os testes da trilha stack (dois ambientes Python + a configuração do coletor + a política no OPA)
	@$(COMPOSE) ps --status running --services 2>/dev/null | grep -qx postgres \
	  || { echo "ERRO: a stack não está no ar. Rode 'make up' antes de 'make test' (o teste de integridade do DAG lê o banco do Airflow)."; exit 1; }
	@mkdir -p data/otel-queue   # sem isto, o Docker criaria data/ como root no bind mount (checkout novo)
	@$(COMPOSE) run --rm --no-deps otel-collector validate --config=/etc/otelcol/config.yaml && echo "ok: configuração do coletor válida (otelcol-contrib validate)"
	@$(COMPOSE) ps --status running --services 2>/dev/null | grep -qx opa \
	  || { echo "ERRO: o OPA não está no ar. Rode 'make up' antes de 'make test' (o teste de equivalência pergunta a ele)."; exit 1; }
	@$(COMPOSE) run --rm --no-deps opa test /policy/guardrails.rego /policy/testes/guardrails_test.rego \
	  casos:/policy/testes/casos.yaml guardrails:/config/guardrails.yaml && echo "ok: testes da política (opa test)"
	$(RUN) 'OTEL_EXPORTER_OTLP_ENDPOINT= PYTHONDONTWRITEBYTECODE=1 $(AGENT)/pytest /opt/agentready/stack/tests -q -p no:cacheprovider --ignore=/opt/agentready/stack/tests/test_dag_integrity.py --ignore=/opt/agentready/stack/tests/test_dag_phase4.py --ignore=/opt/agentready/stack/tests/test_lineage.py'
	$(RUN) 'OTEL_EXPORTER_OTLP_ENDPOINT= PYTHONDONTWRITEBYTECODE=1 STACK_DAGS_DIR=/opt/airflow/dags python -m pytest /opt/agentready/stack/tests/test_dag_integrity.py /opt/agentready/stack/tests/test_dag_phase4.py -q -p no:cacheprovider'

decisoes:  ## Fase 2: decisões do agente desde o último incidente (ou DESDE=HH:MM / DESDE=AAAA-MM-DDTHH:MM), com trace e linhagem
	@$(RUN) 'set -o pipefail; $(AGENT)/agentready-stack decisions --since "$(DESDE)" 2>&1 | sed "\$${/^[{]/d}"'

test-live:  ## Fases 2 a 4: linhagem, traces, fontes, política e snapshots ao vivo (11 execuções; derruba Marquez, Phoenix, coletor e OPA; ~45 min)
	@python3 scripts/lineage_live_check.py

contracts-sync:  ## regenera os testes dbt a partir dos contratos ODCS (arquivos não versionados)
	$(RUN) /opt/agentready/stack/scripts/contracts-sync.sh

run:  ## dispara o DAG (ARGS='{"reset_scenario": true}'; Fase 4: "falhas_upstream": padrao|nenhuma|todas, "fonte_fora_do_ar": ga4|...)
	@token=$$(curl -sf -X POST "$(API)/auth/token" -H 'Content-Type: application/json' \
	   -d '{"username":"instrutor","password":"'"$$(python3 -c 'import json;print(json.load(open("config/passwords.json"))["instrutor"])')"'"}' \
	   | python3 -c 'import json,sys;print(json.load(sys.stdin)["access_token"])') \
	 || { echo "ERRO: não consegui autenticar na API do Airflow ($(API)). A stack está no ar? (make up)"; exit 1; }; \
	 body=$$(python3 -c 'import json,sys;print(json.dumps({"logical_date": None, "conf": json.loads(sys.argv[1])}))' '$(ARGS)'); \
	 curl -sf -X POST "$(API)/api/v2/dags/aurora_midia_diario/dagRuns" -H "Authorization: Bearer $$token" \
	   -H 'Content-Type: application/json' -d "$$body" \
	   | python3 -c 'import json,sys;r=json.load(sys.stdin);print("execução disparada:",r["dag_run_id"],"· estado:",r["state"]);print("acompanhe em $(API)/dags/aurora_midia_diario")' \
	 || { echo "ERRO: o Airflow recusou a execução (veja make logs)"; exit 1; }

observe:  ## Fase 2: os 4 pilares de dados da última execução (o mesmo resumo da tarefa observabilidade.resumo)
	@$(RUN) '$(AGENT)/agentready-stack task observe 2>&1 | sed "\$${/^[{]/d}"' || true

approvals:  ## lista pedidos aguardando aprovação humana (lê o ops.duckdb da trilha stack)
	$(RUN) '$(AGENT)/agentready approvals'

parity:  ## compara as duas trilhas (SCENARIO=manha|pos_backfill|supervisionado|incidente_centavos|incidente_renomeacao|incidente_lote_duplicado|incidente_feed_parado|todos)
	$(RUN) 'OTEL_EXPORTER_OTLP_ENDPOINT= $(AGENT)/agentready-stack parity --scenario $(SCENARIO)'

rollback:  ## desfaz uma alteração do agente (CHG=CHG-xxxx), ligada ao trace da decisão original (Fase 3)
	@[ -n "$(CHG)" ] || { echo "uso: make rollback CHG=CHG-xxxx"; exit 1; }
	@$(RUN) 'set -o pipefail; $(AGENT)/agentready-stack rollback $(CHG) --by instrutor | sed "\$${/^[{]/d}"'

politica:  ## Fase 4: a política permitiria? (ACAO='ajustar C01 5200' | ACAO='pausar C06'); não executa nada
	@set -- $(ACAO); case "$$1" in ajustar) a=adjust_campaign_budget;; pausar) a=pause_campaign;; *) echo "uso: make politica ACAO='ajustar C01 5200' | ACAO='pausar C06'"; exit 1;; esac; \
	 $(RUN) "set -o pipefail; $(AGENT)/agentready-stack politica $$a $$2 $$3 | sed '\$$d'"

politica-testes:  ## Fase 4: testes da política no OPA (cada caso de stack/policy/testes/casos.yaml)
	$(COMPOSE) run --rm --no-deps opa test -v /policy/guardrails.rego /policy/testes/guardrails_test.rego \
	  casos:/policy/testes/casos.yaml guardrails:/config/guardrails.yaml

snapshots:  ## Fase 4: marcos do lake (DuckLake) — snapshots com nome por etapa de cada execução
	@$(RUN) 'set -o pipefail; $(AGENT)/agentready-stack snapshots | sed "\$${/^[{]/d}"'

consultar-em:  ## Fase 4: uma tabela num ponto do lake (TABELA=gold.campaign_daily EM=<snapshot|AAAA-MM-DDTHH:MM> [FILTRO="campaign_id='C01'"])
	@[ -n "$(TABELA)" ] && [ -n "$(EM)" ] || { echo "uso: make consultar-em TABELA=gold.campaign_daily EM=<snapshot|AAAA-MM-DDTHH:MM> [FILTRO=...]"; exit 1; }
	@$(RUN) 'set -o pipefail; $(AGENT)/agentready-stack consultar-em $(TABELA) "$(EM)" $(if $(FILTRO),--filtro "$(FILTRO)",) | sed "\$${/^[{]/d}"'

gold-em:  ## Fase 4: a Gold que o agente leu para uma decisão (DECISAO=<trace_id|CHG-…|REQ-…>)
	@[ -n "$(DECISAO)" ] || { echo "uso: make gold-em DECISAO=<trace_id|CHG-…|REQ-…>"; exit 1; }
	@$(RUN) 'set -o pipefail; $(AGENT)/agentready-stack gold-em $(DECISAO) | sed "\$${/^[{]/d}"'

restaurar:  ## Fase 4: volta as camadas de dados a um snapshot (PARA=<snapshot|CK-…> [MOTIVO=...]); vira um snapshot novo
	@[ -n "$(PARA)" ] || { echo "uso: make restaurar PARA=<snapshot|CK-…> [MOTIVO=...]"; exit 1; }
	@$(RUN) 'set -o pipefail; $(AGENT)/agentready-stack restaurar $(PARA) $(if $(MOTIVO),--motivo "$(MOTIVO)",) | sed "\$${/^[{]/d}"'

fontes:  ## Fase 4: a última carga de cada fonte simulada (status, lotes novos/retirados, linhas, novas tentativas)
	@$(RUN) 'set -o pipefail; $(AGENT)/agentready-stack fontes | sed "\$${/^[{]/d}"'

traces:  ## Fase 3: últimas execuções com o link do trace no Phoenix
	@$(RUN) 'set -o pipefail; $(AGENT)/agentready-stack traces 2>&1 | sed "\$${/^[{]/d}"'

auditoria:  ## Fase 3: verifica a cadeia de hash do log de auditoria da trilha stack
	@$(RUN) '$(AGENT)/agentready verify'

doctor:  ## versões de cada ambiente e compatibilidade do DuckDB
	$(RUN) '$(AGENT)/agentready-stack doctor'

# Bloco 5 (Fase 2): ciclo de vida do incidente na stack (registro no ops.duckdb). Injetar continua sendo um parâmetro
# do DAG (make run ARGS='{"incident": "centavos"}'). `resolver` restaura a Bronze e dispara uma execução:
# o pipeline da trilha padrão nunca roda aqui (pesquisa R8).
INC_ACTION_detectar := detect
INC_ACTION_resolver := resolve
INC_ACTION_revelar := reveal
INC_ACTION_listar := list
incidente:  ## Bloco 5: ACAO=detectar|resolver|revelar|listar (resolver: a fonte volta ao normal e o lake é restaurado)
	@[ -n "$(INC_ACTION_$(ACAO))" ] || { echo "uso: make incidente ACAO=detectar|resolver|revelar|listar"; exit 1; }
	@$(RUN) 'set -o pipefail; $(AGENT)/agentready-stack incident $(INC_ACTION_$(ACAO)) | sed "\$${/^[{]/d}"'
	@if [ "$(ACAO)" = "resolver" ]; then echo "camadas restauradas para o último estado limpo; a próxima execução busca o lote corrigido na fonte"; fi
