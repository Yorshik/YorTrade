import random

from app.utils.runtime import RuntimeState


def _apply_percentage(price: float, percent: float) -> float:
    return round(max(1.0, price * (1.0 + (percent / 100.0))), 2)


async def update_prices(app, game_id: int, state: RuntimeState) -> RuntimeState:
    assets = state.setdefault("assets", {})
    for asset_state in assets.values():
        volatility = float(asset_state["volatility"])
        current_price = float(asset_state["current_price"])
        trend_sign = int(asset_state.get("trend_sign", 1))
        history = asset_state.setdefault("history", [])

        pending_news = asset_state.setdefault("pending_news", [])
        for news_effect in pending_news:
            current_price = _apply_percentage(current_price, float(news_effect["change_percent"]))
        pending_news.clear()

        pending_inside_info = asset_state.setdefault("pending_inside_info", [])
        for inside_effect in pending_inside_info:
            current_price = _apply_percentage(current_price, float(inside_effect["change_percent"]))
        pending_inside_info.clear()

        order_impact = float(asset_state.get("pending_order_impact", 0.0))
        if order_impact:
            current_price = _apply_percentage(current_price, order_impact)
            asset_state["pending_order_impact"] = 0.0

        active_event = asset_state.get("active_event")
        if active_event and active_event.get("ticks_left", 0) > 0:
            event_delta = float(active_event["delta"])
            current_price = round(max(1.0, current_price + event_delta), 2)
            trend_sign = 1 if event_delta >= 0 else -1
            active_event["ticks_left"] -= 1
            if active_event["ticks_left"] <= 0:
                asset_state["active_event"] = None
            asset_state["trend_sign"] = trend_sign
            asset_state["current_price"] = current_price
            history.append(current_price)
            continue

        if random.random() <= 0.3:
            trend_sign *= -1

        move = random.uniform(0.0, volatility)
        if random.random() <= 0.1:
            move *= random.uniform(2.0, 3.0)

        current_price = round(max(1.0, current_price + (move * trend_sign)), 2)

        asset_state["trend_sign"] = trend_sign
        asset_state["current_price"] = current_price
        history.append(current_price)

    return state
