"""Caminhos e carregamento de configuração do projeto."""
from __future__ import annotations

import os
from functools import cache
from pathlib import Path

import yaml

ROOT = Path(os.environ.get("AGENTREADY_HOME", Path(__file__).resolve().parents[2]))
DATA_DIR = ROOT / "data"
DB_PATH = Path(os.environ.get("AGENTREADY_DB", DATA_DIR / "warehouse.duckdb"))
CONTRACTS_DIR = ROOT / "contracts"
SEMANTIC_DIR = ROOT / "semantic"
CONFIG_DIR = ROOT / "config"
CORPUS_DIR = ROOT / "corpus"
TRACES_DIR = Path(os.environ.get("AGENTREADY_TRACES", ROOT / "traces"))


@cache
def load_yaml(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def guardrails() -> dict:
    return load_yaml(CONFIG_DIR / "guardrails.yaml")


def autonomy() -> dict:
    return load_yaml(CONFIG_DIR / "autonomy.yaml")


def model_version_info() -> dict:
    """Versões de tudo que governa uma decisão — gravadas em cada trace para auditoria."""
    info = {f"contract.{p.name.removesuffix('.odcs.yaml')}": load_yaml(p)["version"]
            for p in sorted(CONTRACTS_DIR.glob("*.odcs.yaml"))}
    info["semantic_model"] = load_yaml(SEMANTIC_DIR / "marketing.semantic.yaml")["version"]
    info["guardrails"] = guardrails()["version"]
    info["autonomy"] = autonomy()["version"]
    return info
