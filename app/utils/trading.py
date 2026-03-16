from app.market.models import DealType, GameStatus
from app.utils.log_context import get_update_context
from app.utils.platform import normalize_platform
from app.utils.runtime import load_runtime_state, save_runtime_state


class TradeError(Exception):
    pass


def _impact_percent(amount: int, shares_total: int, direction: int) -> float:
    trade_fraction = amount / max(1, shares_total)
    return round(5.0 * trade_fraction * direction, 2)


async def _resolve_user(app, external_user_id: int, platform: str):
    return await app.users.user.get_by_external(platform, external_user_id)


async def get_active_player_context(app, external_user_id: int, platform: str | None = None):
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


async def _find_active_player_without_runtime(app, external_user_id: int, platform: str) -> tuple[object, object, object]:
    user = await _resolve_user(app, external_user_id, platform)
    if user is None:
        raise TradeError("Пользователь не найден.")

    player = await app.users.player.get_active_by_user(user.id)
    if player is None:
        raise TradeError("У тебя нет активной игры.")

    game = await app.market.game.get_by_id(player.game_id)
    if game and game.status == GameStatus.ACTIVE and str(getattr(game, "platform", platform)).upper() == platform:
        return user, player, game
    raise TradeError("Активная игра не найдена.")


async def execute_trade(
    app,
    external_user_id: int,
    asset_id: int,
    amount: int,
    deal_type: DealType,
    platform: str | None = None,
) -> dict:
    if amount <= 0:
        raise TradeError("Количество должно быть положительным.")

    user, player, game, state = await get_active_player_context(app, external_user_id, platform=platform)
    asset_state = state.get("assets", {}).get(str(asset_id))
    if asset_state is None:
        raise TradeError("Этот актив не участвует в текущей игре.")

    game_asset = await app.market.game_asset.get(game.id, asset_id)
    if game_asset is None:
        raise TradeError("Актив игры не найден.")

    price = float(asset_state["current_price"])
    total_value = round(price * amount, 2)
    portfolio = await app.market.portfolio.get_or_create(player.id, asset_id)

    if deal_type == DealType.BUY:
        if game_asset.shares_available < amount:
            raise TradeError("Недостаточно доступных акций.")
        if player.balance < total_value:
            raise TradeError("Недостаточно баланса.")
        player.balance = round(player.balance - total_value, 2)
        portfolio.amount += amount
        game_asset.shares_available -= amount
        impact_direction = 1
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
        asset_id=asset_id,
        deal_type=deal_type,
        amount=amount,
        price=price,
    )

    asset_state["pending_order_impact"] = round(
        float(asset_state.get("pending_order_impact", 0.0))
        + _impact_percent(amount, game_asset.shares_total, impact_direction),
        2,
    )

    # Track that this player acted on the current tick (for active/passive status)
    last_action_tick = state.setdefault("last_action_tick", {})
    last_action_tick[str(player.id)] = state["tick"]

    await save_runtime_state(app, state)

    return {
        "asset_name": asset_state["name"],
        "amount": amount,
        "price": price,
        "total_value": total_value,
        "balance": player.balance,
        "portfolio_amount": portfolio.amount,
    }


async def build_portfolio_snapshot(app, external_user_id: int, platform: str | None = None) -> dict:
    user, player, game, state = await get_active_player_context(app, external_user_id, platform=platform)
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
        (index for index, row in enumerate(leaderboard, start=1) if row["player_id"] == player.id),
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
            display_name = f"player_{player.id}"
        else:
            display_name = user.username or f"user_{user.platform.lower()}_{user.tg_user_id}"
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


async def leave_active_game(app, external_user_id: int, platform: str | None = None) -> dict:
    context = get_update_context() or {}
    resolved_platform = normalize_platform(platform or context.get("platform"))
    try:
        _, player, game, _ = await get_active_player_context(app, external_user_id, platform=resolved_platform)
        snapshot = await build_portfolio_snapshot(app, external_user_id, platform=resolved_platform)
    except TradeError as exc:
        if str(exc) != "Состояние игры не загружено.":
            raise
        _, player, game = await _find_active_player_without_runtime(app, external_user_id, resolved_platform)
        balance = round(float(player.balance), 2)
        snapshot = {
            "balance": balance,
            "assets_capital": 0.0,
            "total_capital": balance,
        }

    await app.users.player.leave(player, final_capital=snapshot["total_capital"])
    await app.fsm.set_state(external_user_id, app.fsm.FSM.IDLE, platform=resolved_platform)
    min_players = max(1, int(getattr(app.config, "MIN_PLAYERS", 1) or 1))
    active_players = [row for row in await app.users.player.list_by_game(game.id) if row.is_active]
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
