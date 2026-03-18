from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from app.data.models import PhraseType

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
COMPANIES_DATA_PATH = DATA_DIR / "data.json"
EVENT_TEMPLATES_PATH = DATA_DIR / "event_templates.json"
NEWS_DATA_PATH = DATA_DIR / "news.json"
PICTURES_DIR = DATA_DIR / "pictures"

_ALLOWED_DIRECTIONS = {"up", "down"}
_SUPPORTED_IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg")


def _slugify(value: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower())
    return value.strip("-") or "company"


def _read_json_file(path: Path, *, label: str) -> Any:
    if not path.exists():
        raise ValueError(f"Required file is missing: {path} ({label}).")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in {path}: {exc}") from exc


def _normalize_direction(value: object, *, field: str) -> str:
    direction = str(value or "").strip().lower()
    if direction not in _ALLOWED_DIRECTIONS:
        raise ValueError(
            f"Invalid direction in {field}: '{value}'. Expected 'up' or 'down'."
        )
    return direction


def _validated_image_id(value: object) -> str | None:
    if value is None:
        return None
    image_id_raw = str(value).strip()
    if not image_id_raw:
        return None

    image_path = Path(image_id_raw)
    image_id = (
        image_path.stem
        if image_path.suffix.lower() in _SUPPORTED_IMAGE_EXTENSIONS
        else image_id_raw
    )
    if not PICTURES_DIR.exists():
        return image_id

    for extension in _SUPPORTED_IMAGE_EXTENSIONS:
        if (PICTURES_DIR / f"{image_id}{extension}").exists():
            return image_id
    # Also allow extension-less files during migration window.
    if (PICTURES_DIR / image_id).exists():
        return image_id
    return None


def _read_companies_payload() -> list[dict[str, Any]]:
    raw = _read_json_file(COMPANIES_DATA_PATH, label="companies")
    if not isinstance(raw, list) or not raw:
        raise ValueError(
            "Invalid data/data.json: expected non-empty array of companies."
        )

    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            raise ValueError(
                f"Invalid data/data.json item at index {index - 1}: expected object."
            )
        name = str(item.get("name") or "").strip()
        if not name:
            raise ValueError(
                f"Invalid data/data.json item at index {index - 1}: 'name' is required."
            )
        company_id = str(item.get("id") or _slugify(name)).strip()
        if not company_id:
            raise ValueError(
                f"Invalid data/data.json item at index {index - 1}: 'id' is empty."
            )

        if item.get("start_price") is None:
            raise ValueError(
                f"Invalid data/data.json item at index {index - 1}: 'start_price' is required."
            )
        start_price = float(item["start_price"])
        if start_price <= 0:
            raise ValueError(
                f"Invalid data/data.json item at index {index - 1}: 'start_price' must be > 0."
            )

        volatility_raw = float(item.get("volatility") or 0.0)
        normalized.append(
            {
                "company_id": company_id,
                "name": name,
                "start_price": round(start_price, 2),
                "volatility": max(0.0, round(volatility_raw, 2)),
                "image_id": _validated_image_id(item.get("image_id")),
                "growth_phrases": item.get("growth_phrases", []),
                "stable_phrases": item.get("stable_phrases", []),
                "fall_phrases": item.get("fall_phrases", []),
            }
        )
    return normalized


def _read_event_templates_payload() -> list[dict[str, Any]]:
    raw = _read_json_file(EVENT_TEMPLATES_PATH, label="event templates")
    if not isinstance(raw, list):
        raise ValueError(
            "Invalid data/event_templates.json: expected array of templates."
        )

    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            raise ValueError(
                f"Invalid event template at index {index - 1}: expected object."
            )

        template_id = str(item.get("id") or "").strip()
        title = str(item.get("title") or "").strip()
        description = str(item.get("description") or "").strip()
        duration_ticks = int(item.get("duration_ticks") or 1)
        effects_raw = item.get("effects")

        if not template_id:
            raise ValueError(
                f"Invalid event template at index {index - 1}: 'id' is required."
            )
        if not title:
            raise ValueError(
                f"Invalid event template at index {index - 1}: 'title' is required."
            )
        if not description:
            raise ValueError(
                f"Invalid event template at index {index - 1}: 'description' is required."
            )
        if duration_ticks <= 0:
            raise ValueError(
                f"Invalid event template at index {index - 1}: 'duration_ticks' must be > 0."
            )
        if not isinstance(effects_raw, list):
            raise ValueError(
                f"Invalid event template at index {index - 1}: 'effects' must be an array."
            )

        effects: list[dict[str, Any]] = []
        for effect_index, effect_item in enumerate(effects_raw, start=1):
            if not isinstance(effect_item, dict):
                raise ValueError(
                    f"Invalid effect at template[{index - 1}] item[{effect_index - 1}]: expected object."
                )
            company_id = str(effect_item.get("company_id") or "").strip()
            if not company_id:
                raise ValueError(
                    f"Invalid effect at template[{index - 1}] item[{effect_index - 1}]: 'company_id' is required."
                )
            direction = _normalize_direction(
                effect_item.get("direction"),
                field=f"event_templates[{index - 1}].effects[{effect_index - 1}].direction",
            )
            strength = float(effect_item.get("strength") or 0.0)
            if not (0.0 < strength <= 1.0):
                raise ValueError(
                    f"Invalid effect at template[{index - 1}] item[{effect_index - 1}]: 'strength' must be > 0 and <= 1."
                )
            effects.append(
                {
                    "company_id": company_id,
                    "direction": direction,
                    "strength": round(strength, 4),
                }
            )

        normalized.append(
            {
                "id": template_id,
                "title": title,
                "description": description,
                "effects": effects,
                "duration_ticks": duration_ticks,
                "image_id": _validated_image_id(item.get("image_id")),
            }
        )

    return normalized


def load_news_catalog() -> list[dict[str, str]]:
    raw = _read_json_file(NEWS_DATA_PATH, label="news")
    if not isinstance(raw, list):
        raise ValueError("Invalid data/news.json: expected array of news entries.")

    normalized: list[dict[str, str]] = []
    for index, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            raise ValueError(
                f"Invalid news item at index {index - 1}: expected object."
            )
        company_id = str(item.get("company_id") or "").strip()
        if not company_id:
            raise ValueError(
                f"Invalid news item at index {index - 1}: 'company_id' is required."
            )
        direction = _normalize_direction(
            item.get("direction"), field=f"news[{index - 1}].direction"
        )
        text = str(item.get("text") or "").strip()
        if not text:
            raise ValueError(
                f"Invalid news item at index {index - 1}: 'text' is required."
            )
        normalized.append(
            {
                "company_id": company_id,
                "direction": direction,
                "text": text,
            }
        )

    return normalized


async def ensure_market_catalog(app) -> dict[str, Any]:
    companies_payload = _read_companies_payload()
    event_templates_payload = _read_event_templates_payload()
    news_payload = load_news_catalog()

    catalog: list[dict[str, Any]] = []
    for company in companies_payload:
        asset, _ = await app.data.asset.get_or_create(
            name=company["name"],
            base_volatility=float(company["volatility"]),
        )
        catalog.append(
            {
                "company_id": company["company_id"],
                "asset_id": int(asset.id),
                "name": company["name"],
                "volatility": float(company["volatility"]),
                "start_price": float(company["start_price"]),
                "image_id": company["image_id"],
                "growth_phrases": company.get("growth_phrases", []),
                "stable_phrases": company.get("stable_phrases", []),
                "fall_phrases": company.get("fall_phrases", []),
            }
        )

    if event_templates_payload and getattr(getattr(app, "market", None), "runtime", None):
        await app.market.runtime.upsert_event_templates(event_templates_payload)

    return {
        "companies": catalog,
        "event_templates": event_templates_payload,
        "news": news_payload,
    }


async def load_server_data(app) -> dict[str, int]:
    market_payload = await ensure_market_catalog(app)

    stats = {
        "assets_created": 0,
        "phrases_created": 0,
        "event_templates_loaded": len(market_payload["event_templates"]),
        "news_loaded": len(market_payload["news"]),
    }

    for company_payload in market_payload["companies"]:
        asset, asset_created = await app.data.asset.get_or_create(
            name=company_payload["name"],
            base_volatility=float(company_payload["volatility"]),
        )
        stats["assets_created"] += int(asset_created)

        for phrase_type, payload_key in (
            (PhraseType.GROWTH, "growth_phrases"),
            (PhraseType.STABLE, "stable_phrases"),
            (PhraseType.FALL, "fall_phrases"),
        ):
            for phrase in company_payload.get(payload_key, []):
                _, phrase_created = await app.data.phrase.get_or_create(
                    phrase_type=phrase_type,
                    phrase=phrase,
                    asset_id=asset.id,
                )
                stats["phrases_created"] += int(phrase_created)

    return stats


async def _has_loaded_server_data(app) -> bool:
    assets = await app.data.asset.list_all()
    runtime_accessor = getattr(getattr(app, "market", None), "runtime", None)
    if runtime_accessor is None:
        return False
    templates = await runtime_accessor.list_event_templates()
    return bool(assets) and bool(templates)


async def ensure_server_data_loaded(app) -> dict[str, int]:
    if await _has_loaded_server_data(app):
        return {
            "assets_created": 0,
            "phrases_created": 0,
            "event_templates_loaded": 0,
            "news_loaded": 0,
            "skipped": 1,
        }

    stats = await load_server_data(app)
    stats["skipped"] = 0
    return stats
