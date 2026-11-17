"""Settings and YAML config loading. Everything configurable lives in config/*.yaml or env vars."""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
PROMPTS_DIR = ROOT / "prompts"
EVALS_DIR = ROOT / "evals"


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def data_dir() -> Path:
    p = Path(env("DATA_DIR", str(ROOT / "data")))
    p.mkdir(parents=True, exist_ok=True)
    return p


def outputs_dir() -> Path:
    p = Path(env("OUTPUTS_DIR", str(ROOT / "outputs")))
    p.mkdir(parents=True, exist_ok=True)
    return p


def root_decision_log() -> Path:
    return Path(env("DECISION_LOG_PATH", str(ROOT / "decision_log.json")))


@lru_cache(maxsize=None)
def load_yaml(name: str) -> dict[str, Any]:
    with open(CONFIG_DIR / name, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def profile_name() -> str:
    return env("PROFILE", "demo-fast")


def profile() -> dict[str, Any]:
    profiles = load_yaml("models.yaml").get("profiles", {})
    name = profile_name()
    if name not in profiles:
        raise ValueError(f"Unknown PROFILE={name!r}; known: {sorted(profiles)}")
    return profiles[name] or {}


def caps() -> dict[str, int]:
    default = {"results_per_query": 5, "max_queries": 3, "max_pages": 5, "page_chars": 6000,
               "demand_queries": 4, "competitor_queries": 2, "pricing_queries": 2}
    default.update(profile().get("caps", {}))
    return default


def founder_mode() -> str:
    mode = env("FOUNDER_MODE", "explore")
    return mode if mode in {"explore", "delegate", "evaluate"} else "explore"


def gate_definitions() -> dict[str, Any]:
    return load_yaml("gate_definitions.yaml")


def mocks() -> list[dict[str, Any]]:
    return load_yaml("mocks.yaml").get("mocks", [])


def prompt(role: str) -> str:
    path = PROMPTS_DIR / f"{role}.md"
    return path.read_text(encoding="utf-8") if path.exists() else ""
