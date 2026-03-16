import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.clients.common.handlers.leaderboard_handler import LeaderboardHandler
from app.clients.common.handlers.private_game_handler import PrivateGameHandler
from app.clients.common.mailbox import MessageType
from app.web.middlewares.callback_sanity_middleware import CallbackSanityMiddleware


def test_private_handler_prefers_stored_private_message_id(monkeypatch) -> None:
    show_screen_mock = AsyncMock()
    monkeypatch.setattr(
        "app.clients.common.handlers.private_game_handler.show_private_screen",
        show_screen_mock,
    )

    app = SimpleNamespace(
        fsm=SimpleNamespace(
            get_state=AsyncMock(
                return_value=(
                    "playing_main",
                    {"private_message_id": 123, "screen": "main"},
                )
            )
        ),
        sender=SimpleNamespace(answer_callback_query=AsyncMock()),
    )
    handler = PrivateGameHandler(app)
    update = SimpleNamespace(
        type=MessageType.CALLBACK_QUERY,
        source_platform="VK",
        chat_id=2000000001,
        from_user=SimpleNamespace(id=77),
        callback_query=SimpleNamespace(
            id="cb1",
            data="private:main",
            message=SimpleNamespace(
                message_id=999, chat=SimpleNamespace(type="private")
            ),
        ),
    )

    asyncio.run(handler.handle(update))

    show_screen_mock.assert_awaited_once()
    # args: app, tg_user_id, chat_id, screen, data, message_id
    assert show_screen_mock.await_args.args[5] == 123


def test_leaderboard_handler_keeps_existing_market_message_id(monkeypatch) -> None:
    runtime_state = {
        "market_message_id": 777,
        "market_message_pending": False,
        "market_message_pending_since": None,
    }
    monkeypatch.setattr(
        "app.clients.common.handlers.leaderboard_handler.load_runtime_state",
        AsyncMock(return_value=runtime_state),
    )
    save_mock = AsyncMock()
    monkeypatch.setattr(
        "app.clients.common.handlers.leaderboard_handler.save_runtime_state",
        save_mock,
    )
    refresh_mock = AsyncMock()
    monkeypatch.setattr(
        "app.clients.common.handlers.leaderboard_handler.refresh_market_message",
        refresh_mock,
    )

    app = SimpleNamespace(
        market=SimpleNamespace(
            game=SimpleNamespace(
                get_by_chat_id=AsyncMock(return_value=SimpleNamespace(id=9))
            )
        ),
        sender=SimpleNamespace(answer_callback_query=AsyncMock()),
    )
    handler = LeaderboardHandler(app)
    update = SimpleNamespace(
        type=MessageType.CALLBACK_QUERY,
        source_platform="VK",
        chat_id=2000000001,
        from_user=SimpleNamespace(id=77),
        callback_query=SimpleNamespace(
            id="cb2",
            data="group:view_market",
            message=SimpleNamespace(message_id=333),
        ),
    )

    asyncio.run(handler.handle(update))

    assert runtime_state["market_message_id"] == 777
    save_mock.assert_awaited_once_with(app, runtime_state)
    refresh_mock.assert_awaited_once()


def test_callback_sanity_skips_vk_message_id_mismatch() -> None:
    middleware = CallbackSanityMiddleware()
    app = SimpleNamespace(
        fsm=SimpleNamespace(
            get_state=AsyncMock(
                return_value=("playing_main", {"private_message_id": 10})
            )
        ),
        sender=SimpleNamespace(answer_callback_query=AsyncMock()),
    )
    update = SimpleNamespace(
        type=MessageType.CALLBACK_QUERY,
        source_platform="VK",
        from_user=SimpleNamespace(id=1),
        chat_id=2000000001,
        callback_query=SimpleNamespace(
            id="cb3",
            data="private:main",
            message=SimpleNamespace(message_id=999),
        ),
    )

    result = asyncio.run(middleware.process(update, app))

    assert result is None
    app.sender.answer_callback_query.assert_not_awaited()
