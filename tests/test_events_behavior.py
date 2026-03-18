import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.market.models import DealType
from app.utils import trading


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
