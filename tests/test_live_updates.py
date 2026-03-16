import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.utils import live_updates


def test_refresh_private_views_bootstraps_missing_fsm_state(monkeypatch) -> None:
    show_private_screen_mock = AsyncMock()
    monkeypatch.setattr(live_updates, "show_private_screen", show_private_screen_mock)

    app = SimpleNamespace(
        users=SimpleNamespace(
            player=SimpleNamespace(
                list_by_game=AsyncMock(
                    return_value=[SimpleNamespace(id=1, user_id=10, is_active=True)]
                )
            ),
            user=SimpleNamespace(
                get_by_id=AsyncMock(
                    return_value=SimpleNamespace(
                        id=10,
                        tg_user_id=777,
                        platform="VK",
                        dm_chat_id=2000000001,
                    )
                ),
            ),
        ),
        fsm=SimpleNamespace(
            get_state=AsyncMock(return_value=None),
        ),
    )

    state = {"tick": 1}
    asyncio.run(
        live_updates.refresh_private_views(app, game_id=42, state=state, generated=None)
    )

    show_private_screen_mock.assert_awaited_once_with(
        app,
        777,
        2000000001,
        "main",
        {"game_id": 42},
        target_platform="VK",
    )
