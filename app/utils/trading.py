from app.market.models import DealType, GameStatus
from app.utils.achievements import (
    achievement_tracking_enabled,
    apply_achievement_progress,
    build_player_capital_snapshot,
    game_start_balance,
)
from app.utils.log_context import get_update_context
from app.utils.platform import normalize_platform
from app.utils.runtime import load_runtime_state, save_runtime_state


class TradeError(Exception):
    pass


ORDER_IMPACT_BASE_PERCENT = 15.0


def _impact_percent(amount: int, shares_total: int, direction: int) -> float:
    trade_fraction = amount / max(1, shares_total)
    return round(ORDER_IMPACT_BASE_PERCENT * trade_fraction * direction, 2)


async def _resolve_user(app, external_user_id: int, platform: str):
    return await app.users.user.get_by_external(platform, external_user_id)


async def get_active_player_context(
    app, external_user_id: int, platform: str | None = None
):
    context = get_update_context() or {}
    resolved_platform = normalize_platform(platform or context.get("platform"))
    user = await _resolve_user(app, external_user_id, resolved_platform)
    if user is None:
        raise TradeError("Пользователь не найден.")

    player = await app.users.player.get_active_by_user(user.id)
    if player is None:
        raise TradeError("У тебя нет активной игры.")

    game = await app.market.game.get_by_id(player.game_id)
    if not game or game.status != GameStatus.ACTIVE:
        raise TradeError("Активная игра не найдена.")
    if str(getattr(game, "platform", resolved_platform)).upper() != resolved_platform:
        raise TradeError("Активная игра не найдена.")

    state = await load_runtime_state(app, game.id)
    if state is None:
        raise TradeError("Состояние игры не загружено.")
    return user, player, game, state


async def _find_active_player_without_runtime(
    app, external_user_id: int, platform: str
) -> tuple[object, object, object]:
    user = await _resolve_user(app, external_user_id, platform)
    if user is None:
        raise TradeError("Пользователь не найден.")

    player = await app.users.player.get_active_by_user(user.id)
    if player is None:
        raise TradeError("У тебя нет активной игры.")

    game = await app.market.game.get_by_id(player.game_id)
    if (
        game
        and game.status == GameStatus.ACTIVE
        and str(getattr(game, "platform", platform)).upper() == platform
    ):
        return user, player, game
    raise TradeError("Активная игра не найдена.")


async def execute_trade(
    app,
    external_user_id: int,
    asset_id: int | str,
    amount: int,
    deal_type: DealType,
    platform: str | None = None,
) -> dict:
    if amount <= 0:
        raise TradeError("Количество должно быть положительным.")

    _, player, game, state = await get_active_player_context(
        app, external_user_id, platform=platform
    )
    assets_state = state.get("assets", {})
    asset_state = assets_state.get(str(asset_id))
    resolved_asset_id = None
    if asset_state is not None:
        resolved_asset_id = int(asset_state.get("asset_id", asset_id))
    elif not str(asset_id).isdigit():
        for candidate in assets_state.values():
            if str(candidate.get("company_id") or "") == str(asset_id):
                asset_state = candidate
                resolved_asset_id = int(candidate["asset_id"])
                break
    else:
        resolved_asset_id = int(asset_id)
    if asset_state is None:
        raise TradeError("Этот актив не участвует в текущей игре.")
    if resolved_asset_id is None:
        resolved_asset_id = int(asset_state["asset_id"])

    game_asset = await app.market.game_asset.get(game.id, resolved_asset_id)
    if game_asset is None:
        raise TradeError("Актив игры не найден.")

    track_achievements = achievement_tracking_enabled(app)

    active_event = asset_state.get("active_event") or {}
    event_type = str(active_event.get("type") or "")
    event_ticks_left = int(active_event.get("ticks_left", 0) or 0)
    if deal_type == DealType.BUY and event_type == "buyback" and event_ticks_left > 0:
        raise TradeError("Во время выкупа покупка этой акции временно недоступна.")

    price = float(asset_state["current_price"])
    if deal_type == DealType.SELL and event_type == "buyback" and event_ticks_left > 0:
        multiplier = float(active_event.get("sell_multiplier", 1.5))
        price = round(price * multiplier, 2)
    total_value = round(price * amount, 2)
    portfolio = await app.market.portfolio.get_or_create(player.id, resolved_asset_id)
    before_snapshot = None
    if track_achievements:
        before_snapshot = await build_player_capital_snapshot(
            app,
            player_id=player.id,
            balance=float(player.balance),
            assets_state=state.get("assets", {}),
        )

    if deal_type == DealType.BUY:
        if game_asset.shares_available < amount:
            raise TradeError("Недостаточно доступных акций.")
        if player.balance < total_value:
            raise TradeError("Недостаточно баланса.")
        player.balance = round(player.balance - total_value, 2)
        portfolio.amount += amount
        game_asset.shares_available -= amount
        impact_direction = 1
        if event_type == "innovation" and event_ticks_left > 0:
            investors = active_event.setdefault("investors", [])
            investor_id = str(player.id)
            if investor_id not in investors:
                investors.append(investor_id)
    else:
        if portfolio.amount < amount:
            raise TradeError("У тебя нет такого количества акций.")
        player.balance = round(player.balance + total_value, 2)
        portfolio.amount -= amount
        game_asset.shares_available += amount
        impact_direction = -1

    await app.users.player.save(player)
    await app.market.portfolio.save(portfolio)
    await app.market.game_asset.save(game_asset)
    await app.market.deal.create(
        player_id=player.id,
        game_id=game.id,
        asset_id=resolved_asset_id,
        deal_type=deal_type,
        amount=amount,
        price=price,
    )

    trade_impact = _impact_percent(amount, game_asset.shares_total, impact_direction)
    asset_state["pending_order_impact"] = round(
        float(asset_state.get("pending_order_impact", 0.0)) + trade_impact,
        2,
    )

    # Track that this player acted on the current tick (for active/passive status)
    last_action_tick = state.setdefault("last_action_tick", {})
    last_action_tick[str(player.id)] = state["tick"]
    trade_counters = state.setdefault("trade_counters", {})
    player_counter = trade_counters.get(str(player.id))
    current_tick = int(state["tick"])
    if (
        not isinstance(player_counter, dict)
        or int(player_counter.get("tick", -1)) != current_tick
    ):
        player_counter = {"tick": current_tick, "count": 0}
    player_counter["count"] = int(player_counter.get("count", 0)) + 1
    trade_counters[str(player.id)] = player_counter
    trades_this_tick = int(player_counter["count"])

    if track_achievements and before_snapshot is not None:
        after_snapshot = await build_player_capital_snapshot(
            app,
            player_id=player.id,
            balance=float(player.balance),
            assets_state=state.get("assets", {}),
        )
        deal_profit = round(
            float(after_snapshot["total_capital"])
            - float(before_snapshot["total_capital"]),
            2,
        )
        company_share_percent = round(
            (int(portfolio.amount) / max(1, int(game_asset.shares_total))) * 100.0, 4
        )
        start_balance = game_start_balance(game)
        capital_growth_ratio = round(
            float(after_snapshot["total_capital"]) / start_balance, 4
        )

        await apply_achievement_progress(
            app,
            user_id=player.user_id,
            add={"deals_total": 1},
            peak={
                "trades_per_tick_peak": trades_this_tick,
                "deal_profit_peak": deal_profit,
                "impact_peak_percent": abs(trade_impact),
                "portfolio_unique_peak": int(after_snapshot["unique_assets"]),
                "portfolio_total_amount_peak": int(after_snapshot["total_amount"]),
                "company_share_peak_percent": company_share_percent,
                "capital_growth_peak_ratio": capital_growth_ratio,
            },
        )

    await save_runtime_state(app, state)

    return {
        "asset_name": asset_state["name"],
        "amount": amount,
        "price": price,
        "total_value": total_value,
        "balance": player.balance,
        "portfolio_amount": portfolio.amount,
    }


async def build_portfolio_snapshot(
    app, external_user_id: int, platform: str | None = None
) -> dict:
    _, player, game, state = await get_active_player_context(
        app, external_user_id, platform=platform
    )
    portfolio_rows = await app.market.portfolio.list_by_player(player.id)
    assets_state = state.get("assets", {})
    lines = []
    assets_capital = 0.0

    for row in portfolio_rows:
        if row.amount <= 0:
            continue
        asset_state = assets_state.get(str(row.asset_id))
        if asset_state is None:
            continue
        position_value = round(row.amount * float(asset_state["current_price"]), 2)
        assets_capital += position_value
        lines.append(
            {
                "asset_id": row.asset_id,
                "asset_name": asset_state["name"],
                "amount": row.amount,
                "current_price": asset_state["current_price"],
                "capital": position_value,
            }
        )

    total_capital = round(player.balance + assets_capital, 2)
    leaderboard = await build_leaderboard(app, game.id)
    rank = next(
        (
            index
            for index, row in enumerate(leaderboard, start=1)
            if row["player_id"] == player.id
        ),
        None,
    )
    return {
        "player": player,
        "game": game,
        "lines": lines,
        "balance": round(player.balance, 2),
        "assets_capital": round(assets_capital, 2),
        "total_capital": total_capital,
        "rank": rank,
    }


async def build_leaderboard(app, game_id: int) -> list[dict]:
    state = await load_runtime_state(app, game_id)
    assets_state = (state or {}).get("assets", {})
    is_finished = bool(state and state.get("status") == "finished")
    players = await app.users.player.list_by_game(game_id)
    rows = []

    for player in players:
        user = await app.users.user.get_by_id(player.user_id)
        if user is None:
            display_name = f"игрок_{player.id}"
        else:
            display_name = (
                user.username
                or f"пользователь_{user.platform.lower()}_{user.tg_user_id}"
            )
        if player.final_capital is not None and (not player.is_active or is_finished):
            total_capital = round(float(player.final_capital), 2)
        else:
            portfolio_rows = await app.market.portfolio.list_by_player(player.id)
            assets_capital = 0.0
            for row in portfolio_rows:
                if row.amount <= 0:
                    continue
                asset_state = assets_state.get(str(row.asset_id))
                if asset_state is None:
                    continue
                assets_capital += row.amount * float(asset_state["current_price"])
            total_capital = round(float(player.balance) + assets_capital, 2)

        rows.append(
            {
                "player_id": player.id,
                "display_name": display_name,
                "capital": total_capital,
                "is_active": player.is_active,
            }
        )

    rows.sort(key=lambda item: (-item["capital"], item["player_id"]))
    return rows


async def leave_active_game(
    app, external_user_id: int, platform: str | None = None
) -> dict:
    context = get_update_context() or {}
    resolved_platform = normalize_platform(platform or context.get("platform"))
    try:
        _, player, game, _ = await get_active_player_context(
            app, external_user_id, platform=resolved_platform
        )
        snapshot = await build_portfolio_snapshot(
            app, external_user_id, platform=resolved_platform
        )
    except TradeError as exc:
        if str(exc) != "Состояние игры не загружено.":
            raise
        _, player, game = await _find_active_player_without_runtime(
            app, external_user_id, resolved_platform
        )
        balance = round(float(player.balance), 2)
        snapshot = {
            "balance": balance,
            "assets_capital": 0.0,
            "total_capital": balance,
        }

    await app.users.player.leave(player, final_capital=snapshot["total_capital"])
    await app.fsm.set_state(
        external_user_id, app.fsm.FSM.IDLE, platform=resolved_platform
    )
    min_players = max(1, int(getattr(app.config, "MIN_PLAYERS", 1) or 1))
    active_players = [
        row for row in await app.users.player.list_by_game(game.id) if row.is_active
    ]
    game_finished = False
    if game.status == GameStatus.ACTIVE and len(active_players) < min_players:
        await app.game_engine.finish_game(game.id)
        game_finished = True
    return {
        "game_id": game.id,
        "total_capital": snapshot["total_capital"],
        "balance": snapshot["balance"],
        "assets_capital": snapshot["assets_capital"],
        "active_players_left": len(active_players),
        "min_players": min_players,
        "game_finished": game_finished,
    }
