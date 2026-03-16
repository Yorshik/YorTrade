import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.market.models import GameStatus
from app.utils import trading


def test_get_active_player_context_respects_platform() -> None:
    user = SimpleNamespace(id=10)
    player = SimpleNamespace(id=28, user_id=10, game_id=19)
    wrong_platform_game = SimpleNamespace(
        id=19, status=GameStatus.ACTIVE, platform="VK"
    )

    app = SimpleNamespace(
        users=SimpleNamespace(
            user=SimpleNamespace(
                get_by_external=AsyncMock(return_value=user),
            ),
            player=SimpleNamespace(
                get_active_by_user=AsyncMock(return_value=player),
            ),
        ),
        market=SimpleNamespace(
            game=SimpleNamespace(
                get_by_id=AsyncMock(return_value=wrong_platform_game),
            )
        ),
    )

    with pytest.raises(trading.TradeError, match=r"Активная игра не найдена\."):
        asyncio.run(trading.get_active_player_context(app, 737677917, platform="TG"))


def test_get_active_player_context_returns_state_for_matching_platform(
    monkeypatch,
) -> None:
    user = SimpleNamespace(id=10)
    player = SimpleNamespace(id=28, user_id=10, game_id=19)
    game = SimpleNamespace(id=19, status=GameStatus.ACTIVE, platform="TG")
    runtime_state = {"game_id": 19, "tick": 3}

    monkeypatch.setattr(trading, "get_update_context", lambda: None)
    monkeypatch.setattr(
        trading, "load_runtime_state", AsyncMock(return_value=runtime_state)
    )

    app = SimpleNamespace(
        users=SimpleNamespace(
            user=SimpleNamespace(
                get_by_external=AsyncMock(return_value=user),
            ),
            player=SimpleNamespace(
                get_active_by_user=AsyncMock(return_value=player),
            ),
        ),
        market=SimpleNamespace(
            game=SimpleNamespace(
                get_by_id=AsyncMock(return_value=game),
            )
        ),
    )

    resolved_user, resolved_player, resolved_game, state = asyncio.run(
        trading.get_active_player_context(app, 737677917, platform="TG")
    )

    assert resolved_user.id == 10
    assert resolved_player.id == 28
    assert resolved_game.id == 19
    assert state == runtime_state
