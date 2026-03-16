import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.market.models import DealType
from app.utils import events as events_utils, market as market_utils, trading


def test_generate_events_selects_market_crash_after_event_roll(monkeypatch) -> None:
    app = SimpleNamespace(
        market=SimpleNamespace(
            game=SimpleNamespace(
                get_by_id=AsyncMock(
                    return_value=SimpleNamespace(settings={"event_chance": 1.0})
                ),
            )
        )
    )
    state = {
        "tick": 5,
        "assets": {
            "1": {
                "asset_id": 1,
                "name": "Company A",
                "volatility": 5.0,
                "active_event": None,
            },
        },
    }
    monkeypatch.setattr(events_utils.random, "random", lambda: 0.0)
    monkeypatch.setattr(events_utils.random, "choice", lambda options: "market_crash")

    updated_state, event = asyncio.run(
        events_utils.generate_events(app, game_id=1, state=state)
    )

    assert event is not None
    assert event["type"] == "market_crash"
    assert updated_state["global_event"]["type"] == "market_crash"


def test_generate_events_roll_passed_but_asset_event_without_free_assets_returns_none(
    monkeypatch,
) -> None:
    app = SimpleNamespace(
        market=SimpleNamespace(
            game=SimpleNamespace(
                get_by_id=AsyncMock(
                    return_value=SimpleNamespace(settings={"event_chance": 1.0})
                ),
            )
        )
    )
    state = {
        "tick": 5,
        "assets": {
            "1": {
                "asset_id": 1,
                "name": "Company A",
                "volatility": 5.0,
                "active_event": {"type": "trend_reversal", "ticks_left": 3},
            },
        },
    }
    monkeypatch.setattr(events_utils.random, "random", lambda: 0.0)
    monkeypatch.setattr(events_utils.random, "choice", lambda options: "innovation")

    updated_state, event = asyncio.run(
        events_utils.generate_events(app, game_id=1, state=state)
    )

    assert event is None
    assert updated_state["last_event"] is None


def test_update_prices_resolves_innovation_success(monkeypatch) -> None:
    player = SimpleNamespace(id=10, is_active=True, balance=1000.0)
    app = SimpleNamespace(
        users=SimpleNamespace(
            player=SimpleNamespace(
                list_by_game=AsyncMock(return_value=[player]),
                save=AsyncMock(),
            )
        ),
        market=SimpleNamespace(
            portfolio=SimpleNamespace(
                get=AsyncMock(return_value=SimpleNamespace(amount=5)),
            )
        ),
    )
    state = {
        "assets": {
            "1": {
                "asset_id": 1,
                "name": "Company A",
                "volatility": 10.0,
                "current_price": 100.0,
                "trend_sign": 1,
                "history": [100.0],
                "pending_news": [],
                "pending_inside_info": [],
                "pending_order_impact": 0.0,
                "active_event": {
                    "type": "innovation",
                    "ticks_left": 1,
                    "investors": ["10"],
                },
            }
        }
    }
    monkeypatch.setattr(market_utils.random, "random", lambda: 0.1)
    monkeypatch.setattr(market_utils.random, "uniform", lambda _a, _b: 10.0)

    updated_state, tick_events = asyncio.run(
        market_utils.update_prices(app, game_id=1, state=state)
    )

    assert updated_state["assets"]["1"]["active_event"] is None
    assert updated_state["assets"]["1"]["current_price"] == 110.0
    assert player.balance == 1025.0
    assert tick_events[0]["type"] == "innovation_result"
    assert "успех" in tick_events[0]["text"]


def test_update_prices_applies_dividends_and_price_drop() -> None:
    player = SimpleNamespace(id=10, is_active=True, balance=1000.0)
    app = SimpleNamespace(
        users=SimpleNamespace(
            player=SimpleNamespace(
                list_by_game=AsyncMock(return_value=[player]),
                save=AsyncMock(),
            )
        ),
        market=SimpleNamespace(
            portfolio=SimpleNamespace(
                get=AsyncMock(return_value=SimpleNamespace(amount=10)),
            )
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

    updated_state, tick_events = asyncio.run(
        market_utils.update_prices(app, game_id=1, state=state)
    )

    assert updated_state["assets"]["1"]["active_event"] is None
    assert updated_state["assets"]["1"]["current_price"] == 99.8
    assert player.balance == 1020.0
    assert tick_events[0]["type"] == "dividends_result"


def test_update_prices_applies_market_crash_drop(monkeypatch) -> None:
    app = SimpleNamespace()
    state = {
        "global_event": {"type": "market_crash", "ticks_left": 2},
        "assets": {
            "1": {
                "asset_id": 1,
                "name": "Company A",
                "volatility": 10.0,
                "current_price": 100.0,
                "trend_sign": 1,
                "history": [100.0],
                "pending_news": [],
                "pending_inside_info": [],
                "pending_order_impact": 0.0,
                "active_event": {
                    "type": "trend_reversal",
                    "ticks_left": 1,
                    "delta": 0.0,
                },
            }
        },
    }
    monkeypatch.setattr(market_utils.random, "uniform", lambda _a, _b: 5.0)

    updated_state, tick_events = asyncio.run(
        market_utils.update_prices(app, game_id=1, state=state)
    )

    assert updated_state["assets"]["1"]["current_price"] == 95.0
    assert updated_state["global_event"]["ticks_left"] == 1
    assert tick_events == []


def test_execute_trade_blocks_buy_when_buyback_active(monkeypatch) -> None:
    player = SimpleNamespace(id=10, balance=1000.0)
    game = SimpleNamespace(id=50)
    state = {
        "tick": 3,
        "assets": {
            "1": {
                "asset_id": 1,
                "name": "Company A",
                "current_price": 100.0,
                "pending_order_impact": 0.0,
                "active_event": {
                    "type": "buyback",
                    "ticks_left": 3,
                    "sell_multiplier": 1.5,
                },
            }
        },
    }
    app = SimpleNamespace(
        market=SimpleNamespace(
            game_asset=SimpleNamespace(
                get=AsyncMock(
                    return_value=SimpleNamespace(
                        shares_available=100, shares_total=1000
                    )
                ),
            )
        ),
    )
    monkeypatch.setattr(
        trading,
        "get_active_player_context",
        AsyncMock(return_value=(SimpleNamespace(id=1), player, game, state)),
    )

    with pytest.raises(trading.TradeError, match="выкупа"):
        asyncio.run(
            trading.execute_trade(
                app,
                external_user_id=777,
                asset_id=1,
                amount=1,
                deal_type=DealType.BUY,
                platform="TG",
            )
        )


def test_execute_trade_uses_buyback_sell_multiplier(monkeypatch) -> None:
    player = SimpleNamespace(id=10, balance=100.0)
    game = SimpleNamespace(id=50)
    portfolio = SimpleNamespace(amount=10)
    game_asset = SimpleNamespace(shares_available=100, shares_total=1000)
    state = {
        "tick": 3,
        "assets": {
            "1": {
                "asset_id": 1,
                "name": "Company A",
                "current_price": 100.0,
                "pending_order_impact": 0.0,
                "active_event": {
                    "type": "buyback",
                    "ticks_left": 3,
                    "sell_multiplier": 1.5,
                },
            }
        },
    }
    app = SimpleNamespace(
        users=SimpleNamespace(
            player=SimpleNamespace(save=AsyncMock()),
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
    monkeypatch.setattr(
        trading,
        "get_active_player_context",
        AsyncMock(return_value=(SimpleNamespace(id=1), player, game, state)),
    )
    monkeypatch.setattr(trading, "save_runtime_state", AsyncMock(return_value=state))

    result = asyncio.run(
        trading.execute_trade(
            app,
            external_user_id=777,
            asset_id=1,
            amount=2,
            deal_type=DealType.SELL,
            platform="TG",
        )
    )

    assert result["price"] == 150.0
    assert result["total_value"] == 300.0
    assert player.balance == 400.0
    assert portfolio.amount == 8
    assert game_asset.shares_available == 102


def test_execute_trade_tracks_innovation_investors(monkeypatch) -> None:
    player = SimpleNamespace(id=10, balance=500.0)
    game = SimpleNamespace(id=50)
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
                "active_event": {
                    "type": "innovation",
                    "ticks_left": 5,
                    "investors": [],
                },
            }
        },
    }
    app = SimpleNamespace(
        users=SimpleNamespace(
            player=SimpleNamespace(save=AsyncMock()),
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
    monkeypatch.setattr(
        trading,
        "get_active_player_context",
        AsyncMock(return_value=(SimpleNamespace(id=1), player, game, state)),
    )
    monkeypatch.setattr(trading, "save_runtime_state", AsyncMock(return_value=state))

    asyncio.run(
        trading.execute_trade(
            app,
            external_user_id=777,
            asset_id=1,
            amount=1,
            deal_type=DealType.BUY,
            platform="TG",
        )
    )

    assert "10" in state["assets"]["1"]["active_event"]["investors"]
