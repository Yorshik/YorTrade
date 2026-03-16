import random


async def generate_inside_info(
    app, game_id: int, state: dict
) -> tuple[dict, dict | None]:
    game = await app.market.game.get_by_id(game_id)
    settings = (game.settings or {}) if game else {}
    insider_chance = float(settings.get("insider_chance_per_player_per_tick", 0.25))
    assets = list(state.get("assets", {}).values())
    if not assets or random.random() > insider_chance:
        state["last_insider_info"] = None
        return state, None

    asset_state = random.choice(assets)
    direction = random.choice([-1, 1])
    volatility = float(asset_state["volatility"])
    true_change = round(random.uniform(volatility, volatility * 2) * direction, 1)

    # The forecast told to players may be in the wrong direction (50% chance)
    told_change = true_change if random.random() < 0.5 else -true_change

    asset_state.setdefault("pending_inside_info", []).append(
        {
            "change_percent": true_change,
            "source_tick": state["tick"],
        }
    )

    insider_info = {
        "tick": state["tick"],
        "asset_name": asset_state["name"],
        "asset_id": asset_state["asset_id"],
        "forecast_percent": told_change,
        "true_change_percent": true_change,
    }
    state["last_insider_info"] = insider_info
    return state, insider_info
