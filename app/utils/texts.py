from __future__ import annotations

import json
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
TEXTS_PATH = DATA_DIR / "texts.json"

_DEFAULT_TEXT = (
    "Привет! Я бот для симуляции фондового рынка.\n"
    "Команды: /start_game (в группе), /game или /market (в личке), /ping."
)


def load_text(key: str, fallback_key: str | None = None) -> str:
    try:
        payload = json.loads(TEXTS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return _DEFAULT_TEXT

    if not isinstance(payload, dict):
        return _DEFAULT_TEXT

    value = payload.get(key)
    if isinstance(value, str) and value.strip():
        return value

    if fallback_key:
        fallback_value = payload.get(fallback_key)
        if isinstance(fallback_value, str) and fallback_value.strip():
            return fallback_value

    return _DEFAULT_TEXT
