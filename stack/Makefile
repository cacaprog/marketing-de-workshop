# Trilha stack — comandos. Rode a partir de stack/.  `make help` lista tudo.
SHELL := /bin/bash
-include .env            # mesmas variáveis que o docker compose lê (AIRFLOW_PORT, TZ, ...)
export AIRFLOW_UID ?= $(shell id -u)
COMPOSE := docker compose
# O entrypoint oficial só executa direto comandos 'bash'/'python'; o resto vira 'airflow ...'.
RUN := $(COMPOSE) run --rm --no-deps airflow-scheduler bash -c
AGENT := /opt/venvs/agent/bin
AIRFLOW_PORT ?= 8080
API := http://localhost:$(AIRFLOW_PORT)
SCENARIO ?= todos
ARGS ?= {}
SVC ?= airflow-scheduler

.PHONY: help check up down reset logs test run approvals parity contracts-sync doctor

help:  ## lista os comandos
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | sed 's/:.*## /\t/' | column -t -s $$'\t'

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
	@mkdir -p data
	$(COMPOSE) up -d --build --wait
	@echo; echo "Stack no ar: $(API)"; \
	 echo "Usuários (só para estudo local): instrutor/instrutor (dispara execuções) · aprovadora/aprovadora (aprova ações)"

down:  ## para os serviços e mantém os dados
	$(COMPOSE) down

reset:  ## para tudo e APAGA os dados da trilha stack (warehouse, traces, Postgres)
	$(COMPOSE) down -v
	@docker run --rm -v "$(CURDIR)/data:/d" alpine sh -c 'rm -rf /d/* /d/.[!.]* 2>/dev/null; true'
	@echo "dados da trilha stack apagados (a trilha padrão em ../data não foi tocada)"

logs:  ## acompanha os logs de um serviço (SVC=airflow-scheduler)
	$(COMPOSE) logs -f $(SVC)

test:  ## roda os testes da trilha stack (dois ambientes Python)
	$(RUN) 'PYTHONDONTWRITEBYTECODE=1 $(AGENT)/pytest /opt/agentready/stack/tests -q -p no:cacheprovider --ignore=/opt/agentready/stack/tests/test_dag_integrity.py'
	$(RUN) 'PYTHONDONTWRITEBYTECODE=1 STACK_DAGS_DIR=/opt/airflow/dags python -m pytest /opt/agentready/stack/tests/test_dag_integrity.py -q -p no:cacheprovider'

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

approvals:  ## lista pedidos aguardando aprovação humana (lê o warehouse da trilha stack)
	$(RUN) '$(AGENT)/agentready approvals'
