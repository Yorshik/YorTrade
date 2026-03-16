import random

from app.utils.achievements import (
    achievement_tracking_enabled,
    apply_achievement_progress,
    build_player_capital_snapshot,
    game_start_balance,
)
from app.utils.runtime import RuntimeState


def _apply_percentage(price: float, percent: float) -> float:
    return round(max(1.0, price * (1.0 + (percent / 100.0))), 2)


def _as_player_ids(raw_ids: object) -> set[int]:
    if not isinstance(raw_ids, list):
        return set()
    result: set[int] = set()
    for raw in raw_ids:
        try:
            result.add(int(raw))
        except TypeError, ValueError:
            continue
    return result


async def _refresh_capital_growth_peaks(app, game_id: int, state: RuntimeState) -> None:
    if not achievement_tracking_enabled(app):
        return
    game = await app.market.game.get_by_id(game_id)
    if game is None:
        return

    start_balance = game_start_balance(game)
    assets_state = state.get("assets", {})
    players = await app.users.player.list_by_game(game_id)
    for player in players:
        if not player.is_active:
            continue
        snapshot = await build_player_capital_snapshot(
            app,
            player_id=player.id,
            balance=float(player.balance),
            assets_state=assets_state,
        )
        growth_ratio = round(float(snapshot["total_capital"]) / start_balance, 4)
        await apply_achievement_progress(
            app,
            user_id=player.user_id,
            peak={"capital_growth_peak_ratio": growth_ratio},
        )


async def _resolve_innovation_event(
    app,
    game_id: int,
    asset_state: dict,
    active_event: dict,
    current_price: float,
    trend_sign: int,
) -> tuple[float, int, dict]:
    success = random.random() < 0.5
    investors = _as_player_ids(active_event.get("investors"))
    affected_players = 0
    cash_flow = 0.0

    players = await app.users.player.list_by_game(game_id)
    for player in players:
        if not player.is_active:
            continue
        if investors and player.id not in investors:
            continue

        portfolio = await app.market.portfolio.get(
            player.id, int(asset_state["asset_id"])
        )
        amount = int(getattr(portfolio, "amount", 0) or 0)
        if amount <= 0:
            continue

        position_value = round(amount * current_price, 2)
        if success:
            cash_delta = round(position_value * 0.05, 2)
            if cash_delta <= 0:
                continue
            player.balance = round(float(player.balance) + cash_delta, 2)
        else:
            cash_delta = round(position_value * 0.03, 2)
            cash_delta = min(cash_delta, float(player.balance))
            if cash_delta <= 0:
                continue
            player.balance = round(float(player.balance) - cash_delta, 2)

        await app.users.player.save(player)
        affected_players += 1
        cash_flow += cash_delta

    volatility = float(asset_state["volatility"])
    if volatility > 0:
        resolution_percent = round(random.uniform(volatility, volatility * 2), 1)
    else:
        resolution_percent = 0.0
    price_percent = resolution_percent if success else -resolution_percent
    if price_percent:
        current_price = _apply_percentage(current_price, price_percent)
        trend_sign = 1 if price_percent >= 0 else -1

    outcome_label = "успех" if success else "неудача"
    reward_label = "бонусы" if success else "штрафы"
    notification = {
        "type": "innovation_result",
        "asset_id": asset_state["asset_id"],
        "asset_name": asset_state["name"],
        "ticks_left": 0,
        "include_remaining": False,
        "text": (
            f"{asset_state['name']}: инновация — {outcome_label}. "
            f"{reward_label} {cash_flow:.2f}$ для {affected_players} игроков, "
            f"цена {price_percent:+.1f}%."
        ),
    }
    return current_price, trend_sign, notification


async def _apply_dividends_event(
    app,
    game_id: int,
    asset_state: dict,
    active_event: dict,
    assets_state: dict[str, dict],
    current_price: float,
    trend_sign: int,
) -> tuple[float, int, dict]:
    payout_rate = max(0.0, float(active_event.get("payout_rate", 0.02)))
    players = await app.users.player.list_by_game(game_id)
    total_payout = 0.0
    recipients = 0
    payouts_by_player_id: dict[int, float] = {}

    for player in players:
        if not player.is_active:
            continue
        portfolio = await app.market.portfolio.get(
            player.id, int(asset_state["asset_id"])
        )
        amount = int(getattr(portfolio, "amount", 0) or 0)
        if amount <= 0:
            continue
        payout = round(payout_rate * current_price * amount, 2)
        if payout <= 0:
            continue
        player.balance = round(float(player.balance) + payout, 2)
        await app.users.player.save(player)
        payouts_by_player_id[player.id] = payout
        total_payout += payout
        recipients += 1

    total_payout = round(total_payout, 2)
    drop_percent = 0.0
    if total_payout > 0:
        drop_percent = round(min(30.0, total_payout / 100.0), 2)
        current_price = _apply_percentage(current_price, -drop_percent)
        trend_sign = -1

    if payouts_by_player_id and achievement_tracking_enabled(app):
        game = await app.market.game.get_by_id(game_id)
        start_balance = game_start_balance(game) if game is not None else 1000.0
        price_override = {int(asset_state["asset_id"]): current_price}
        for player in players:
            payout = float(payouts_by_player_id.get(player.id, 0.0))
            if payout <= 0:
                continue
            snapshot = await build_player_capital_snapshot(
                app,
                player_id=player.id,
                balance=float(player.balance),
                assets_state=assets_state,
                asset_price_overrides=price_override,
            )
            growth_ratio = round(
                float(snapshot["total_capital"]) / max(1.0, start_balance), 4
            )
            await apply_achievement_progress(
                app,
                user_id=player.user_id,
                add={"dividends_total": payout},
                peak={"capital_growth_peak_ratio": growth_ratio},
            )

    notification = {
        "type": "dividends_result",
        "asset_id": asset_state["asset_id"],
        "asset_name": asset_state["name"],
        "ticks_left": 0,
        "include_remaining": False,
        "text": (
            f"{asset_state['name']}: дивиденды {total_payout:.2f}$ "
            f"({recipients} игроков), цена {-drop_percent:+.2f}%."
        ),
    }
    return current_price, trend_sign, notification


async def update_prices(
    app, game_id: int, state: RuntimeState
) -> tuple[RuntimeState, list[dict]]:
    assets = state.setdefault("assets", {})
    tick_events: list[dict] = []
    global_event = state.get("global_event")
    crash_active = bool(
        global_event
        and global_event.get("type") == "market_crash"
        and int(global_event.get("ticks_left", 0)) > 0
    )

    for asset_state in assets.values():
        volatility = float(asset_state["volatility"])
        current_price = float(asset_state["current_price"])
        trend_sign = int(asset_state.get("trend_sign", 1))
        history = asset_state.setdefault("history", [])

        pending_news = asset_state.setdefault("pending_news", [])
        for news_effect in pending_news:
            current_price = _apply_percentage(
                current_price, float(news_effect["change_percent"])
            )
        pending_news.clear()

        pending_inside_info = asset_state.setdefault("pending_inside_info", [])
        for inside_effect in pending_inside_info:
            current_price = _apply_percentage(
                current_price, float(inside_effect["change_percent"])
            )
        pending_inside_info.clear()

        order_impact = float(asset_state.get("pending_order_impact", 0.0))
        if order_impact:
            current_price = _apply_percentage(current_price, order_impact)
            asset_state["pending_order_impact"] = 0.0

        handled_price = False
        active_event = asset_state.get("active_event")
        if active_event and int(active_event.get("ticks_left", 0)) > 0:
            event_type = str(active_event.get("type") or "trend_reversal")
            if event_type == "trend_reversal":
                event_delta = float(active_event.get("delta", 0.0))
                current_price = round(max(1.0, current_price + event_delta), 2)
                trend_sign = 1 if event_delta >= 0 else -1
                active_event["ticks_left"] = int(active_event.get("ticks_left", 0)) - 1
                if int(active_event.get("ticks_left", 0)) <= 0:
                    asset_state["active_event"] = None
                handled_price = True
            elif event_type == "innovation":
                active_event["ticks_left"] = int(active_event.get("ticks_left", 0)) - 1
                if int(active_event.get("ticks_left", 0)) <= 0:
                    (
                        current_price,
                        trend_sign,
                        notification,
                    ) = await _resolve_innovation_event(
                        app,
                        game_id,
                        asset_state,
                        active_event,
                        current_price,
                        trend_sign,
                    )
                    tick_events.append(notification)
                    asset_state["active_event"] = None
                    handled_price = True
            elif event_type == "dividends":
                active_event["ticks_left"] = int(active_event.get("ticks_left", 0)) - 1
                if int(active_event.get("ticks_left", 0)) <= 0:
                    (
                        current_price,
                        trend_sign,
                        notification,
                    ) = await _apply_dividends_event(
                        app,
                        game_id,
                        asset_state,
                        active_event,
                        state.get("assets", {}),
                        current_price,
                        trend_sign,
                    )
                    tick_events.append(notification)
                    asset_state["active_event"] = None
                    handled_price = True
            elif event_type == "buyback":
                active_event["ticks_left"] = int(active_event.get("ticks_left", 0)) - 1
                if int(active_event.get("ticks_left", 0)) <= 0:
                    asset_state["active_event"] = None
            else:
                event_delta = float(active_event.get("delta", 0.0))
                current_price = round(max(1.0, current_price + event_delta), 2)
                trend_sign = 1 if event_delta >= 0 else -1
                active_event["ticks_left"] = int(active_event.get("ticks_left", 0)) - 1
                if int(active_event.get("ticks_left", 0)) <= 0:
                    asset_state["active_event"] = None
                handled_price = True

        if not handled_price:
            if random.random() <= 0.3:
                trend_sign *= -1

            move = random.uniform(0.0, volatility)
            if random.random() <= 0.1:
                move *= random.uniform(2.0, 3.0)

            current_price = round(max(1.0, current_price + (move * trend_sign)), 2)

        if crash_active:
            crash_percent = round(random.uniform(0.0, volatility / 2.0), 2)
            if crash_percent > 0:
                current_price = _apply_percentage(current_price, -crash_percent)
                trend_sign = -1

        asset_state["trend_sign"] = trend_sign
        asset_state["current_price"] = current_price
        history.append(current_price)

    if crash_active and global_event is not None:
        global_event["ticks_left"] = int(global_event.get("ticks_left", 0)) - 1
        if int(global_event.get("ticks_left", 0)) <= 0:
            state["global_event"] = None

    await _refresh_capital_growth_peaks(app, game_id, state)

    return state, tick_events
