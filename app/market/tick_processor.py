from __future__ import annotations

import random
from math import ceil, floor

from app.market.models import MarketDirection
from app.utils.runtime import RuntimeState

BASE_CURVE = [0.5, 0.8, 1.0, 1.0, 0.8, 0.5]
NOISE_MIN = -0.002
NOISE_MAX = 0.002
MAX_CHANGE_PER_TICK = 0.1


def _direction_sign(direction: str | MarketDirection | None) -> int:
    if isinstance(direction, MarketDirection):
        return 1 if direction == MarketDirection.UP else -1
    return 1 if str(direction or "").lower() == "up" else -1


def _scaled_curve(duration_ticks: int) -> list[float]:
    duration = max(1, int(duration_ticks))
    if duration == 1:
        return [1.0]
    points = len(BASE_CURVE)
    values: list[float] = []
    for index in range(duration):
        position = (index * (points - 1)) / (duration - 1)
        lo = floor(position)
        hi = ceil(position)
        if lo == hi:
            values.append(float(BASE_CURVE[lo]))
            continue
        ratio = position - lo
        interpolated = BASE_CURVE[lo] * (1.0 - ratio) + BASE_CURVE[hi] * ratio
        values.append(float(interpolated))
    return values


def _curve_multiplier(start_tick: int, end_tick: int, current_tick: int) -> float:
    duration = max(1, int(end_tick) - int(start_tick) + 1)
    step_index = min(max(0, int(current_tick) - int(start_tick)), duration - 1)
    return _scaled_curve(duration)[step_index]


def _normalize_effects(raw_effects: object) -> dict:
    if isinstance(raw_effects, dict):
        return dict(raw_effects)

    # New event template format stores company effects as a top-level list.
    if isinstance(raw_effects, list):
        return {"companies": [item for item in raw_effects if isinstance(item, dict)]}

    return {}


def _event_effect_for_company(active_event, template, company_id: str) -> float:
    effects = _normalize_effects(getattr(template, "effects", None))

    explicit_strength = active_event.strength
    explicit_direction = (active_event.meta or {}).get("direction")

    companies_effect = effects.get("companies")
    if isinstance(companies_effect, dict) and company_id in companies_effect:
        value = companies_effect[company_id]
        if isinstance(value, dict):
            strength = float(value.get("strength", 0.0) or 0.0)
            direction = value.get("direction")
        else:
            strength = float(value or 0.0)
            direction = None
        if direction is not None and strength >= 0:
            return abs(strength) * _direction_sign(direction)
        return strength

    if isinstance(companies_effect, list):
        for item in companies_effect:
            if not isinstance(item, dict):
                continue
            if str(item.get("company_id")) != company_id:
                continue
            strength = float(item.get("strength", 0.0) or 0.0)
            direction = item.get("direction")
            if direction is not None and strength >= 0:
                return abs(strength) * _direction_sign(direction)
            return strength

    if explicit_strength and active_event.company_id and str(active_event.company_id) == company_id:
        if explicit_direction is not None and explicit_strength >= 0:
            return abs(float(explicit_strength)) * _direction_sign(explicit_direction)
        return float(explicit_strength)

    generic_strength = float(effects.get("strength", 0.0) or 0.0)
    generic_direction = effects.get("direction")
    if generic_strength != 0.0:
        if generic_direction is not None and generic_strength >= 0:
            return abs(generic_strength) * _direction_sign(generic_direction)
        return generic_strength

    if explicit_strength and not active_event.company_id:
        if explicit_direction is not None and explicit_strength >= 0:
            return abs(float(explicit_strength)) * _direction_sign(explicit_direction)
        return float(explicit_strength)

    return 0.0


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def _company_asset_map(state: RuntimeState) -> dict[str, dict]:
    assets = state.get("assets") or {}
    mapping: dict[str, dict] = {}
    for asset in assets.values():
        company_id = str(asset.get("company_id") or asset.get("asset_id"))
        mapping[company_id] = asset
    return mapping


async def process_tick(
    app,
    game_id: int,
    state: RuntimeState,
) -> tuple[RuntimeState, list[dict]]:
    tick = int(state.get("tick", 0))
    companies = await app.market.runtime.list_companies(game_id)
    companies_map = {str(company.id): company for company in companies}

    active_events = await app.market.runtime.list_active_events_for_tick(game_id, tick)
    templates = {template.id: template for template in await app.market.runtime.list_event_templates()}
    news_rows = await app.market.runtime.list_news_for_tick(game_id, tick)
    insider_rows = await app.market.runtime.list_insider_for_tick(game_id, tick)

    news_by_company: dict[str, list] = {}
    for news in news_rows:
        news_by_company.setdefault(str(news.company_id), []).append(news)

    insider_by_company: dict[str, list] = {}
    for insider in insider_rows:
        insider_by_company.setdefault(str(insider.company_id), []).append(insider)

    events_by_company: dict[str, list] = {}
    for active_event in active_events:
        template = templates.get(active_event.template_id)
        if template is None:
            continue
        if active_event.company_id:
            events_by_company.setdefault(str(active_event.company_id), []).append(
                (active_event, template)
            )
            continue

        # Global event affects companies described by template.effects, or all if omitted.
        effects = _normalize_effects(template.effects)
        companies_effect = effects.get("companies")
        if isinstance(companies_effect, dict):
            target_ids = [str(item) for item in companies_effect]
        elif isinstance(companies_effect, list):
            target_ids = [
                str(item.get("company_id"))
                for item in companies_effect
                if isinstance(item, dict) and item.get("company_id") is not None
            ]
        else:
            target_ids = list(companies_map.keys())

        for target_id in target_ids:
            events_by_company.setdefault(target_id, []).append((active_event, template))

    asset_by_company = _company_asset_map(state)
    history_rows: list[dict] = []
    updated_prices: dict[str, float] = {}
    tick_events: list[dict] = []

    for company_id, company in sorted(companies_map.items(), key=lambda item: item[0]):
        price = float(company.current_price)
        total_ratio = 0.0
        asset = asset_by_company.get(company_id)

        for active_event, template in events_by_company.get(company_id, []):
            strength = _event_effect_for_company(active_event, template, company_id)
            if strength == 0.0:
                continue
            multiplier = _curve_multiplier(
                active_event.start_tick,
                active_event.end_tick,
                tick,
            )
            total_ratio += strength * multiplier
            ticks_left = max(0, int(active_event.end_tick) - tick)
            tick_events.append(
                {
                    "tick": tick,
                    "type": "market_event",
                    "event_id": str(active_event.id),
                    "template_id": active_event.template_id,
                    "asset_name": (
                        asset_by_company.get(company_id, {}).get("name")
                        or str(company.name)
                    ),
                    "text": str((active_event.meta or {}).get("title") or template.title),
                    "ticks_left": ticks_left,
                    "include_remaining": True,
                }
            )

        for news in news_by_company.get(company_id, []):
            total_ratio += _direction_sign(news.direction) * float(news.strength)

        for insider in insider_by_company.get(company_id, []):
            base_sign = _direction_sign(insider.direction)
            effective_sign = base_sign if insider.is_true else -base_sign
            total_ratio += effective_sign * float(insider.strength)

        if asset is not None:
            order_impact_percent = float(asset.get("pending_order_impact", 0.0) or 0.0)
            if order_impact_percent:
                total_ratio += order_impact_percent / 100.0
                asset["pending_order_impact"] = 0.0

        total_ratio += random.uniform(NOISE_MIN, NOISE_MAX)
        total_ratio = _clamp(total_ratio, -MAX_CHANGE_PER_TICK, MAX_CHANGE_PER_TICK)

        next_price = round(max(1.0, price * (1.0 + total_ratio)), 2)
        updated_prices[company_id] = next_price
        history_rows.append(
            {
                "game_id": game_id,
                "company_id": company_id,
                "tick": tick,
                "price": next_price,
            }
        )

        if asset is not None:
            history = asset.setdefault("history", [])
            history.append(next_price)
            asset["current_price"] = next_price

    await app.market.runtime.update_company_prices(game_id, updated_prices)
    await app.market.runtime.append_price_history(history_rows)
    await app.market.runtime.delete_finished_events(game_id, tick)

    return state, tick_events
