from __future__ import annotations

import hashlib
import random

from app.utils.data_loader import load_news_catalog
from app.utils.runtime import RuntimeState


def _seed(*parts: object) -> int:
    raw = "|".join(str(part) for part in parts)
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return int(digest[:16], 16)


def _rng(*parts: object) -> random.Random:
    return random.Random(_seed(*parts))


def _asset_name_by_company(state: RuntimeState, company_id: str) -> str:
    for asset in (state.get("assets") or {}).values():
        if str(asset.get("company_id") or "") == company_id:
            return str(asset.get("name") or company_id)
    return company_id


def _direction_sign(direction: str) -> int:
    return 1 if str(direction).lower() == "up" else -1


def _percent_to_strength(percent: float) -> float:
    return round(max(0.0, float(percent)) / 100.0, 4)


def _pick_company(companies: list, rng: random.Random):
    if not companies:
        return None
    index = int(rng.random() * len(companies))
    return companies[min(index, len(companies) - 1)]


async def schedule_market_drivers(
    app,
    game_id: int,
    state: RuntimeState,
) -> tuple[RuntimeState, dict[str, object]]:
    """Deterministically schedule event/news/insider rows for the current tick."""

    tick = int(state.get("tick", 0))
    game = await app.market.game.get_by_id(game_id)
    settings = (game.settings or {}) if game else {}

    companies = await app.market.runtime.list_companies(game_id)
    companies = sorted(companies, key=lambda row: str(row.id))
    company_map = {str(company.id): company for company in companies}
    templates = await app.market.runtime.list_event_templates()
    news_catalog = load_news_catalog()

    generated: dict[str, object] = {
        "event": None,
        "events": [],
        "news": None,
        "news_image_id": None,
        "insider": None,
    }

    # 1) Activate event template (multi-tick)
    event_rng = _rng("event", game_id, tick)
    event_chance = float(settings.get("event_chance", 0.5))
    if templates and event_rng.random() <= event_chance:
        template_index = int(event_rng.random() * len(templates))
        template = templates[min(template_index, len(templates) - 1)]

        duration_ticks = max(1, int(template.duration_ticks or 1))
        event_id = f"evt:{game_id}:{tick}:{template.id}"
        await app.market.runtime.create_active_event(
            {
                "id": event_id,
                "game_id": game_id,
                "template_id": str(template.id),
                "company_id": None,
                "strength": 0.0,
                "start_tick": tick,
                "end_tick": tick + duration_ticks - 1,
                "meta": {
                    "title": template.title,
                    "description": template.description,
                    "image_id": template.image_id,
                },
            }
        )

        event_payload = {
            "tick": tick,
            "type": "market_event",
            "event_id": event_id,
            "template_id": str(template.id),
            "asset_name": "рынок",
            "text": str(template.title),
            "ticks_left": max(0, duration_ticks - 1),
            "include_remaining": True,
            "delta": None,
            "image_id": template.image_id,
        }
        generated["event"] = event_payload
        generated["events"] = [event_payload]
        state["last_event"] = event_payload
    else:
        state["last_event"] = None

    # 2) Instant news for current tick
    news_rng = _rng("news", game_id, tick)
    news_chance = float(settings.get("news_chance", 0.5))
    available_news = [
        item for item in news_catalog if str(item["company_id"]) in company_map
    ]
    if available_news and news_rng.random() <= news_chance:
        selected_index = int(news_rng.random() * len(available_news))
        selected = available_news[min(selected_index, len(available_news) - 1)]
        company = company_map.get(str(selected["company_id"]))
        if company is not None:
            company_volatility = max(0.5, float(company.volatility or 0.0))
            news_move_percent = round(
                _rng("news-strength", game_id, tick, selected["company_id"]).uniform(
                    0.5, company_volatility
                ),
                1,
            )
            strength = _percent_to_strength(news_move_percent)
            direction = str(selected["direction"])
            news_id = f"news:{game_id}:{tick}:{selected['company_id']}:{direction}"
            await app.market.runtime.create_news(
                {
                    "id": news_id,
                    "game_id": game_id,
                    "company_id": str(selected["company_id"]),
                    "direction": direction,
                    "strength": strength,
                    "tick": tick,
                }
            )
            generated["news"] = str(selected["text"])
            generated["news_image_id"] = f"{selected['company_id']}_{direction}"
            last_news = state.setdefault("last_news", [])
            last_news.append(str(selected["text"]))
            del last_news[:-5]
        else:
            generated["news"] = None
            generated["news_image_id"] = None
    else:
        generated["news"] = None
        generated["news_image_id"] = None

    # 3) Delayed insider info
    insider_rng = _rng("insider", game_id, tick)
    insider_chance = float(settings.get("insider_chance_per_player_per_tick", 0.25))
    if companies and insider_rng.random() <= insider_chance:
        company = _pick_company(companies, _rng("insider-company", game_id, tick))
        if company is not None:
            direction = "up" if insider_rng.random() >= 0.5 else "down"
            company_volatility = max(0.5, float(company.volatility or 0.0))
            insider_move_percent = round(
                _rng("insider-strength", game_id, tick, company.id).uniform(
                    0.5, company_volatility
                ),
                1,
            )
            strength = _percent_to_strength(insider_move_percent)
            target_tick = tick + 1
            is_true = insider_rng.random() < 0.5
            insider_id = f"insider:{game_id}:{tick}:{company.id}:{target_tick}"
            await app.market.runtime.create_insider_info(
                {
                    "id": insider_id,
                    "game_id": game_id,
                    "company_id": str(company.id),
                    "direction": direction,
                    "strength": strength,
                    "target_tick": target_tick,
                    "is_true": is_true,
                }
            )

            forecast_percent = _direction_sign(direction) * insider_move_percent
            rumor_direction = "вырастет" if direction == "up" else "упадет"
            insider_text = (
                "На рынке ходят слухи, что "
                f"{_asset_name_by_company(state, str(company.id))} "
                f"{rumor_direction} на {insider_move_percent:.1f}% в ближайшее время"
            )
            insider_payload = {
                "tick": tick,
                "asset_name": _asset_name_by_company(state, str(company.id)),
                "asset_id": company.id,
                "forecast_percent": forecast_percent,
                "true_change_percent": forecast_percent if is_true else -forecast_percent,
                "target_tick": target_tick,
                "is_true": is_true,
                "text": insider_text,
                "image_id": "insider_info",
            }
            generated["insider"] = insider_payload
            state["last_insider_info"] = insider_payload
        else:
            state["last_insider_info"] = None
    else:
        state["last_insider_info"] = None

    return state, generated
