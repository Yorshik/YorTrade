import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.market import engine as engine_module
from app.market.models import DealType, GameStatus
from app.utils import (
    achievements as achievements_utils,
    market as market_utils,
    trading,
)


def test_apply_achievement_progress_unlocks_expected_levels() -> None:
    stats_row = SimpleNamespace(user_id=1, **achievements_utils.DEFAULT_STATS)
    app = SimpleNamespace(
        users=SimpleNamespace(
            achievement=SimpleNamespace(
                get_or_create=AsyncMock(return_value=stats_row),
                save=AsyncMock(return_value=stats_row),
            ),
            user=SimpleNamespace(
                get_by_id=AsyncMock(return_value=SimpleNamespace(dm_chat_id=None)),
            ),
            player=SimpleNamespace(),
        ),
        sender=SimpleNamespace(send_message=AsyncMock()),
    )

    unlocks = asyncio.run(
        achievements_utils.apply_achievement_progress(
            app,
            user_id=1,
            add={"deals_total": 10},
            peak={"impact_peak_percent": 3.0},
        )
    )

    assert stats_row.deals_total == 10
    assert stats_row.impact_peak_percent == 3.0
    assert any(
        item["title"] == "Количество сделок" and item["level"] == "I"
        for item in unlocks
    )
    assert any(item["title"] == "Импакт" and item["level"] == "II" for item in unlocks)
    app.users.achievement.save.assert_awaited_once()


def test_execute_trade_updates_achievements_when_tracking_enabled(monkeypatch) -> None:
    player = SimpleNamespace(id=10, user_id=77, balance=1000.0)
    game = SimpleNamespace(id=50, settings={"default_balance": 1000})
    portfolio = SimpleNamespace(amount=0)
    game_asset = SimpleNamespace(shares_available=100, shares_total=1000)
    state = {
        "tick": 3,
        "assets": {
            "1": {
                "asset_id": 1,
                "name": "Company A",
                "current_price": 100.0,
                "pending_order_impact": 0.0,
                "active_event": None,
            }
        },
    }
    app = SimpleNamespace(
        users=SimpleNamespace(
            player=SimpleNamespace(save=AsyncMock()),
            achievement=object(),
        ),
        market=SimpleNamespace(
            game_asset=SimpleNamespace(
                get=AsyncMock(return_value=game_asset),
                save=AsyncMock(return_value=game_asset),
            ),
            portfolio=SimpleNamespace(
                get_or_create=AsyncMock(return_value=portfolio),
                save=AsyncMock(return_value=portfolio),
            ),
            deal=SimpleNamespace(create=AsyncMock()),
        ),
    )
    apply_progress_mock = AsyncMock()
    snapshot_mock = AsyncMock(
        side_effect=[
            {"total_capital": 1000.0, "unique_assets": 0, "total_amount": 0},
            {"total_capital": 1020.0, "unique_assets": 1, "total_amount": 2},
        ]
    )
    monkeypatch.setattr(
        trading,
        "get_active_player_context",
        AsyncMock(return_value=(SimpleNamespace(id=1), player, game, state)),
    )
    monkeypatch.setattr(trading, "save_runtime_state", AsyncMock(return_value=state))
    monkeypatch.setattr(trading, "apply_achievement_progress", apply_progress_mock)
    monkeypatch.setattr(trading, "build_player_capital_snapshot", snapshot_mock)

    asyncio.run(
        trading.execute_trade(
            app,
            external_user_id=777,
            asset_id=1,
            amount=2,
            deal_type=DealType.BUY,
            platform="TG",
        )
    )

    assert apply_progress_mock.await_count == 1
    call_kwargs = apply_progress_mock.await_args.kwargs
    assert call_kwargs["user_id"] == 77
    assert call_kwargs["add"] == {"deals_total": 1}
    assert call_kwargs["peak"]["trades_per_tick_peak"] == 1
    assert call_kwargs["peak"]["deal_profit_peak"] == 20.0
    assert call_kwargs["peak"]["impact_peak_percent"] == 0.03
    assert call_kwargs["peak"]["portfolio_unique_peak"] == 1
    assert call_kwargs["peak"]["portfolio_total_amount_peak"] == 2
    assert call_kwargs["peak"]["company_share_peak_percent"] == 0.2
    assert call_kwargs["peak"]["capital_growth_peak_ratio"] == 1.02
    assert state["trade_counters"]["10"]["count"] == 1


def test_update_prices_dividends_updates_achievement_progress(monkeypatch) -> None:
    player = SimpleNamespace(id=10, user_id=77, is_active=True, balance=1000.0)
    app = SimpleNamespace(
        users=SimpleNamespace(
            player=SimpleNamespace(
                list_by_game=AsyncMock(return_value=[player]),
                save=AsyncMock(),
            ),
            achievement=object(),
        ),
        market=SimpleNamespace(
            game=SimpleNamespace(
                get_by_id=AsyncMock(
                    return_value=SimpleNamespace(settings={"default_balance": 1000})
                )
            ),
            portfolio=SimpleNamespace(
                get=AsyncMock(return_value=SimpleNamespace(amount=10)),
            ),
        ),
    )
    state = {
        "assets": {
            "1": {
                "asset_id": 1,
                "name": "Company A",
                "volatility": 5.0,
                "current_price": 100.0,
                "trend_sign": 1,
                "history": [100.0],
                "pending_news": [],
                "pending_inside_info": [],
                "pending_order_impact": 0.0,
                "active_event": {
                    "type": "dividends",
                    "ticks_left": 1,
                    "payout_rate": 0.02,
                },
            }
        }
    }
    apply_progress_mock = AsyncMock()
    monkeypatch.setattr(market_utils, "apply_achievement_progress", apply_progress_mock)
    monkeypatch.setattr(
        market_utils,
        "build_player_capital_snapshot",
        AsyncMock(
            return_value={
                "total_capital": 1200.0,
                "unique_assets": 1,
                "total_amount": 10,
            }
        ),
    )
    monkeypatch.setattr(market_utils, "_refresh_capital_growth_peaks", AsyncMock())

    updated_state, _ = asyncio.run(
        market_utils.update_prices(app, game_id=1, state=state)
    )

    assert updated_state["assets"]["1"]["active_event"] is None
    assert player.balance == 1020.0
    assert apply_progress_mock.await_count == 1
    call_kwargs = apply_progress_mock.await_args.kwargs
    assert call_kwargs["user_id"] == 77
    assert call_kwargs["add"] == {"dividends_total": 20.0}
    assert call_kwargs["peak"]["capital_growth_peak_ratio"] == 1.2


def test_finish_game_awards_win_achievement(monkeypatch) -> None:
    game = SimpleNamespace(
        id=1,
        chat_id=-1001,
        platform="TG",
        status=GameStatus.ACTIVE,
        ended_at=None,
    )
    player_one = SimpleNamespace(id=1, user_id=101, balance=1000.0, is_active=True)
    player_two = SimpleNamespace(id=2, user_id=102, balance=1000.0, is_active=True)
    user_one = SimpleNamespace(
        id=101, username="A", platform="TG", tg_user_id=1, dm_chat_id=None
    )
    user_two = SimpleNamespace(
        id=102, username="B", platform="TG", tg_user_id=2, dm_chat_id=None
    )

    async def _user_by_id(user_id: int):
        return {101: user_one, 102: user_two}.get(user_id)

    async def _portfolio_by_player(player_id: int):
        if player_id == 1:
            return []
        return [SimpleNamespace(asset_id=1, amount=2)]

    app = SimpleNamespace(
        market=SimpleNamespace(
            game=SimpleNamespace(
                get_by_id=AsyncMock(return_value=game),
                save=AsyncMock(return_value=game),
            ),
            portfolio=SimpleNamespace(
                list_by_player=AsyncMock(side_effect=_portfolio_by_player),
            ),
        ),
        users=SimpleNamespace(
            player=SimpleNamespace(
                list_by_game=AsyncMock(return_value=[player_one, player_two]),
                leave=AsyncMock(),
            ),
            user=SimpleNamespace(get_by_id=AsyncMock(side_effect=_user_by_id)),
            achievement=object(),
        ),
        fsm=SimpleNamespace(
            FSM=SimpleNamespace(IDLE="idle"),
            set_state=AsyncMock(),
        ),
    )
    apply_progress_mock = AsyncMock()
    monkeypatch.setattr(
        engine_module, "apply_achievement_progress", apply_progress_mock
    )
    monkeypatch.setattr(engine_module, "save_runtime_state", AsyncMock())
    monkeypatch.setattr(engine_module, "refresh_market_message", AsyncMock())

    game_engine = engine_module.GameEngine(app)
    game_engine._notify_game_finished = AsyncMock()

    asyncio.run(
        game_engine._finish_game(
            1,
            state={
                "status": "running",
                "assets": {"1": {"current_price": 200.0}},
            },
        )
    )

    assert apply_progress_mock.await_count == 1
    call_kwargs = apply_progress_mock.await_args.kwargs
    assert call_kwargs["user_id"] == 102
    assert call_kwargs["add"] == {"wins_total": 1}
