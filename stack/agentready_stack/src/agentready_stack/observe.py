"""Resumo dos 4 pilares de dados desta execução (Fase 2, FR-004b): a tabela que o `agentready observe`
da trilha padrão imprimia, agora lida de meta.observability_checks (os modelos dbt `obs_*`).

Também monta o relatório web do Elementary (`edr report`). Uma falha ao montar o relatório é só um
aviso: os vereditos e o resumo já existem (caso de borda "report build fails").
"""
from __future__ import annotations

import os
import subprocess

from agentready.db import rows

ICON = {"pass": "✅", "warn": "⚠️", "fail": "❌"}
REPORT_FILE = os.environ.get("STACK_REPORT_FILE", "/opt/stack-data/elementary/index.html")


class ObservabilityAlert(RuntimeError):
    """Algum pilar falhou nesta execução: a tarefa-folha fica vermelha (o agente não depende dela)."""


def verdicts(con) -> list[dict]:
    return rows(con, """SELECT pillar, target, status, observed, baseline, ratio, detail, reference_ts
                        FROM meta.observability_checks
                        ORDER BY CASE pillar WHEN 'frescor' THEN 1 WHEN 'volume' THEN 2
                                             WHEN 'distribuição' THEN 3 ELSE 4 END, target""")


def table(vs: list[dict]) -> str:
    lines = ["pilar | alvo | ok | detalhe"]
    lines += [f"{v['pillar']} | {v['target']} | {ICON[v['status']]} | {v['detail']}" for v in vs]
    return "\n".join(lines)


def build_report() -> dict:
    """Roda `edr report` no venv do dbt. Nunca levanta exceção: devolve ok=False e avisa no log."""
    edr = os.environ.get("STACK_EDR_BIN", "/opt/venvs/dbt/bin/edr")
    project = os.environ.get("DBT_PROJECT_DIR", "/opt/airflow/dbt/aurora")
    profiles = os.environ.get("DBT_PROFILES_DIR", project)
    cmd = [edr, "report", "--file-path", REPORT_FILE, "--project-dir", project, "--profiles-dir", profiles,
           "--open-browser", "false", "--target-path", os.environ.get("STACK_EDR_TARGET", "/tmp/edr_target"),
           # sem `dbt deps` (pacotes vêm da imagem; offline) e sem telemetria: stack/config/edr/config.yml
           "--config-dir", os.environ.get("STACK_EDR_CONFIG_DIR", "/opt/airflow/config/edr")]
    try:
        # O projeto dbt INTERNO do edr fica no site-packages (somente leitura com o UID do container):
        # o target/ dele vai para /tmp.
        env = os.environ | {"EDR_INTERNAL_TARGET_PATH": os.environ.get("EDR_INTERNAL_TARGET_PATH", "/tmp/edr_internal_target")}
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=600, env=env)
        err = None if r.returncode == 0 else (r.stderr or r.stdout)[-1500:]
    except (OSError, subprocess.TimeoutExpired) as e:
        err = str(e)
    if err:
        print(f"relatório de observabilidade não atualizado: {err.strip()}", flush=True)
        return {"ok": False, "error": err.strip()[-300:]}
    print(f"Relatório de observabilidade atualizado: {REPORT_FILE} "
          f"(http://localhost:{os.environ.get('REPORT_PORT', '8090')})", flush=True)
    return {"ok": True, "file": REPORT_FILE}
