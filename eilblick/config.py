"""Configuration loading and shared paths."""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
ASSETS = ROOT / "assets"
FONTS = ASSETS / "fonts"
STATE_DIR = ROOT / "state"

# Temporary media folder. Lives only inside the GitHub runner for one run:
# wiped before every build and again after the upload. Never committed.
TMP = Path(os.environ.get("EILBLICK_TMP", ROOT / "tmp_media"))


@lru_cache
def settings() -> dict:
    with open(CONFIG_DIR / "settings.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def keywords() -> dict:
    """config/keywords.yaml – most-searched keywords from the owner (optional file)."""
    try:
        with open(CONFIG_DIR / "keywords.yaml", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except FileNotFoundError:
        return {}


@lru_cache
def sources() -> dict:
    with open(CONFIG_DIR / "sources.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def env(name: str, required: bool = True) -> str | None:
    val = os.environ.get(name)
    if required and not val:
        raise RuntimeError(f"Missing secret / environment variable: {name}")
    return val


UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
)
HEADERS = {"User-Agent": UA, "Accept-Language": "de-DE,de;q=0.9,en;q=0.5"}
