import random
from datetime import datetime, timedelta, timezone

from app.utils.data_loader import ensure_market_catalog
from app.utils.lobby import normalize_game_settings
from app.utils.runtime import RuntimeState, save_runtime_state


def _random_volatility(global_volatility: float) -> float:
    max_step = max(1, round(global_volatility * 10))
    return round(random.randint(1, max_step) / 10, 1)


def _build_asset_runtime(company: dict, start_price: float, volatility: float) -> dict:
    initial_direction = random.choice([-1, 1])
    return {
        "asset_id": int(company["asset_id"]),
        "company_id": str(company["company_id"]),
        "name": str(company["name"]),
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
    market_catalog = await ensure_market_catalog(app)
    companies = list(market_catalog.get("companies") or [])
    if not companies:
        raise ValueError("Нет компаний в каталоге для старта игры.")

    selected_companies = companies
    await app.market.game_asset.delete_by_game(game.id)

    started_at = datetime.now(timezone.utc)
    state: RuntimeState = {
        "game_id": game.id,
        "chat_id": game.chat_id,
        "platform": str(getattr(game, "platform", "TG")).upper(),
        "tick": 0,
        "next_tick_at": (
            started_at + timedelta(seconds=int(settings["tick_seconds"]))
        ).isoformat(),
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

    db_companies: list[dict] = []
    price_history_rows: list[dict] = []

    for company in selected_companies:
        configured_price = float(company.get("start_price") or 0.0)
        if configured_price <= 0.0:
            raise ValueError(
                f"У компании '{company.get('name')}' не задана стартовая цена."
            )
        start_price = round(configured_price, 2)
        volatility = _random_volatility(settings["global_volatility"])
        await app.market.game_asset.create(
            game_id=game.id,
            asset_id=int(company["asset_id"]),
            company_id=str(company["company_id"]),
            start_price=start_price,
            volatility=volatility,
            shares_total=settings["max_shares_per_asset"],
            shares_available=settings["max_shares_per_asset"],
        )
        state["assets"][str(company["asset_id"])] = _build_asset_runtime(
            company,
            start_price=start_price,
            volatility=volatility,
        )
        db_companies.append(
            {
                "id": str(company["company_id"]),
                "name": str(company["name"]),
                "current_price": start_price,
                "volatility": volatility,
            }
        )
        price_history_rows.append(
            {
                "game_id": game.id,
                "company_id": str(company["company_id"]),
                "tick": 0,
                "price": start_price,
            }
        )

    await app.market.runtime.set_companies(game.id, db_companies)
    await app.market.runtime.append_price_history(price_history_rows)

    await save_runtime_state(app, state)
    return state
