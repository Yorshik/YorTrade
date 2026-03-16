import random
from datetime import UTC, datetime, timedelta

from app.utils.lobby import normalize_game_settings
from app.utils.runtime import RuntimeState, save_runtime_state


def _random_volatility(global_volatility: float) -> float:
    max_step = max(1, round(global_volatility * 10))
    return round(random.randint(1, max_step) / 10, 1)


def _build_asset_runtime(asset, start_price: float, volatility: float) -> dict:
    initial_direction = random.choice([-1, 1])
    return {
        "asset_id": asset.id,
        "name": asset.name,
        "current_price": start_price,
        "start_price": start_price,
        "volatility": volatility,
        "history": [start_price],
        "trend_sign": initial_direction,
        "pending_news": [],
        "active_event": None,
        "pending_order_impact": 0.0,
        "pending_inside_info": [],
    }


async def initialize_game_market(
    app, game, chat_title: str | None = None
) -> RuntimeState:
    settings = normalize_game_settings(game.settings)
    assets = await app.data.asset.list_all()
    companies_amount = int(settings.get("companies_amount") or 0)
    if companies_amount <= 0:
        raise ValueError("Количество компаний для игры не задано.")
    if len(assets) < companies_amount:
        raise ValueError("Недостаточно компаний в базе для старта игры.")

    selected_assets = random.sample(assets, companies_amount)
    await app.market.game_asset.delete_by_game(game.id)

    started_at = datetime.now(UTC)
    state: RuntimeState = {
        "game_id": game.id,
        "chat_id": game.chat_id,
        "platform": str(getattr(game, "platform", "TG")).upper(),
        "tick": 0,
        "status": "running",
        "market_view": "main",
        "market_message_id": None,
        "market_message_pending": False,
        "market_message_pending_since": None,
        "last_news": [],
        "last_event": None,
        "last_insider_info": None,
        "global_event": None,
        "inside_info_by_player": {},
        "assets": {},
        "chat_title": chat_title,
        "game_started_at": started_at.isoformat(),
        "game_duration_seconds": int(settings["game_duration_minutes"] * 60),
        "ends_at": (
            started_at + timedelta(minutes=settings["game_duration_minutes"])
        ).isoformat(),
        "updated_at": None,
    }

    for asset in selected_assets:
        start_price = round(
            random.uniform(settings["min_start_price"], settings["max_start_price"]),
            2,
        )
        volatility = _random_volatility(settings["global_volatility"])
        await app.market.game_asset.create(
            game_id=game.id,
            asset_id=asset.id,
            start_price=start_price,
            volatility=volatility,
            shares_total=settings["max_shares_per_asset"],
            shares_available=settings["max_shares_per_asset"],
        )
        state["assets"][str(asset.id)] = _build_asset_runtime(
            asset,
            start_price=start_price,
            volatility=volatility,
        )

    await save_runtime_state(app, state)
    return state
