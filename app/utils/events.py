import random

from app.utils.runtime import RuntimeState


async def generate_events(app, game_id: int, state: RuntimeState) -> tuple[RuntimeState, dict | None]:
    game = await app.market.game.get_by_id(game_id)
    settings = (game.settings or {}) if game else {}
    event_chance = float(settings.get("event_chance", 0.5))
    assets = [
        asset for asset in state.get("assets", {}).values()
        if not asset.get("active_event")
    ]

    if not assets or random.random() > event_chance:
        state["last_event"] = None
        return state, None

    asset_state = random.choice(assets)
    current_sign = int(asset_state.get("trend_sign", 1))
    new_sign = -current_sign if random.random() < 0.7 else current_sign
    volatility = float(asset_state["volatility"])
    delta = round(random.uniform(1.5 * volatility, 2.5 * volatility) * new_sign, 2)
    asset_state["active_event"] = {
        "ticks_left": 6,
        "delta": delta,
        "source_tick": state["tick"],
    }
    event = {
        "tick": state["tick"],
        "type": "trend_reversal",
        "asset_name": asset_state["name"],
        "delta": delta,
        "ticks_left": 6,
    }
    state["last_event"] = event
    return state, event
