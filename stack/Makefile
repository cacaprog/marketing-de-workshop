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
API := http://localhost:$(AIRFLOW_PORT)
SCENARIO ?= todos
ARGS ?= {}
SVC ?= airflow-scheduler

.PHONY: help check up down reset logs test run approvals parity contracts-sync doctor rollback incidente observe test-live decisoes traces auditoria

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
	@mkdir -p data data/otel-queue
	$(COMPOSE) up -d --build --wait --remove-orphans
	@$(RUN) '$(AGENT)/agentready-stack doctor'
	@echo; echo "Stack no ar:"; \
	 echo "  Airflow (DAG, aprovações) ..... $(API)"; \
	 echo "  Linhagem (Marquez) ............ http://localhost:$(MARQUEZ_WEB_PORT)"; \
	 echo "  Relatório de observabilidade .. http://localhost:$(REPORT_PORT)"; \
	 echo "  Traces (Phoenix) .............. http://localhost:$(PHOENIX_PORT)"; \
	 echo "Usuários (só para estudo local): instrutor/instrutor (dispara execuções) · aprovadora/aprovadora (aprova ações)"

down:  ## para os serviços e mantém os dados
	$(COMPOSE) down

reset:  ## para tudo e APAGA os dados da trilha stack (warehouse, traces, Postgres, linhagem, relatório, Phoenix)
	$(COMPOSE) down -v
	@docker run --rm -v "$(CURDIR)/data:/d" alpine sh -c 'rm -rf /d/* /d/.[!.]* 2>/dev/null; true'
	@echo "dados da trilha stack apagados: warehouse, log de auditoria, histórico de linhagem (Marquez), relatório, traces (Phoenix) e a fila do coletor (a trilha padrão em ../data não foi tocada)"

logs:  ## acompanha os logs de um serviço (SVC=airflow-scheduler)
	$(COMPOSE) logs -f $(SVC)

test:  ## roda os testes da trilha stack (dois ambientes Python + a configuração do coletor)
	@mkdir -p data/otel-queue   # sem isto, o Docker criaria data/ como root no bind mount (checkout novo)
	@$(COMPOSE) run --rm --no-deps otel-collector validate --config=/etc/otelcol/config.yaml && echo "ok: configuração do coletor válida (otelcol-contrib validate)"
	$(RUN) 'OTEL_EXPORTER_OTLP_ENDPOINT= PYTHONDONTWRITEBYTECODE=1 $(AGENT)/pytest /opt/agentready/stack/tests -q -p no:cacheprovider --ignore=/opt/agentready/stack/tests/test_dag_integrity.py --ignore=/opt/agentready/stack/tests/test_lineage.py'
	$(RUN) 'OTEL_EXPORTER_OTLP_ENDPOINT= PYTHONDONTWRITEBYTECODE=1 STACK_DAGS_DIR=/opt/airflow/dags python -m pytest /opt/agentready/stack/tests/test_dag_integrity.py -q -p no:cacheprovider'

decisoes:  ## Fase 2: decisões do agente desde o último incidente (ou DESDE=HH:MM / DESDE=AAAA-MM-DDTHH:MM), com trace e linhagem
	@$(RUN) 'set -o pipefail; $(AGENT)/agentready-stack decisions --since "$(DESDE)" 2>&1 | sed "\$${/^[{]/d}"'

test-live:  ## Fases 2 e 3: linhagem e traces ao vivo (7 execuções em shadow; derruba Marquez, Phoenix e coletor; ~30 min)
	@python3 scripts/lineage_live_check.py

contracts-sync:  ## regenera os testes dbt a partir dos contratos ODCS (arquivos não versionados)
	$(RUN) /opt/agentready/stack/scripts/contracts-sync.sh

run:  ## dispara o DAG (ARGS='{"reset_scenario": true}')
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

approvals:  ## lista pedidos aguardando aprovação humana (lê o warehouse da trilha stack)
	$(RUN) '$(AGENT)/agentready approvals'

parity:  ## compara as duas trilhas (SCENARIO=manha|pos_backfill|supervisionado|incidente_centavos|incidente_renomeacao|incidente_lote_duplicado|incidente_feed_parado|todos)
	$(RUN) 'OTEL_EXPORTER_OTLP_ENDPOINT= $(AGENT)/agentready-stack parity --scenario $(SCENARIO)'

rollback:  ## desfaz uma alteração do agente (CHG=CHG-xxxx), ligada ao trace da decisão original (Fase 3)
	@[ -n "$(CHG)" ] || { echo "uso: make rollback CHG=CHG-xxxx"; exit 1; }
	@$(RUN) 'set -o pipefail; $(AGENT)/agentready-stack rollback $(CHG) --by instrutor | sed "\$${/^[{]/d}"'

traces:  ## Fase 3: últimas execuções com o link do trace no Phoenix
	@$(RUN) 'set -o pipefail; $(AGENT)/agentready-stack traces 2>&1 | sed "\$${/^[{]/d}"'

auditoria:  ## Fase 3: verifica a cadeia de hash do log de auditoria da trilha stack
	@$(RUN) '$(AGENT)/agentready verify'

doctor:  ## versões de cada ambiente e compatibilidade do DuckDB
	$(RUN) '$(AGENT)/agentready-stack doctor'

# Bloco 5 (Fase 2): ciclo de vida do incidente no warehouse da stack. Injetar continua sendo um parâmetro
# do DAG (make run ARGS='{"incident": "centavos"}'). `resolver` restaura a Bronze e dispara uma execução:
# o pipeline da trilha padrão nunca roda aqui (pesquisa R8).
INC_ACTION_detectar := detect
INC_ACTION_resolver := resolve
INC_ACTION_revelar := reveal
INC_ACTION_listar := list
incidente:  ## Bloco 5: ACAO=detectar|resolver|revelar|listar (resolver dispara uma execução do DAG)
	@[ -n "$(INC_ACTION_$(ACAO))" ] || { echo "uso: make incidente ACAO=detectar|resolver|revelar|listar"; exit 1; }
	@$(RUN) 'set -o pipefail; $(AGENT)/agentready-stack incident $(INC_ACTION_$(ACAO)) | sed "\$${/^[{]/d}"'
	@if [ "$(ACAO)" = "resolver" ]; then echo "reconstruindo as camadas com o lote original..."; $(MAKE) --no-print-directory run ARGS='{}'; fi
