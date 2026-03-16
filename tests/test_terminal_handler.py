import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.clients.common.handlers.end_game_handler import EndGameHandler
from app.clients.common.mailbox import Update


def _build_group_update(
    text: str, *, user_id: int = 101, platform: str = "TG"
) -> Update:
    return Update.model_validate(
        {
            "update_id": 1,
            "message": {
                "message_id": 10,
                "from": {
                    "id": user_id,
                    "is_bot": False,
                    "first_name": "Tester",
                    "username": "tester",
                },
                "chat": {
                    "id": -777,
                    "type": "group",
                },
                "text": text,
                "new_chat_members": [],
            },
            "source_platform": platform,
        }
    )


def test_stop_command_finishes_game_for_host() -> None:
    app = SimpleNamespace(
        config=SimpleNamespace(PREFIX="/"),
        market=SimpleNamespace(
            game=SimpleNamespace(
                get_by_chat_id=AsyncMock(
                    return_value=SimpleNamespace(id=55, host_id=5001)
                )
            )
        ),
        users=SimpleNamespace(
            user=SimpleNamespace(
                get_by_external=AsyncMock(return_value=SimpleNamespace(id=5001))
            )
        ),
        sender=SimpleNamespace(answer_callback_query=AsyncMock()),
        game_engine=SimpleNamespace(finish_game=AsyncMock()),
    )
    handler = EndGameHandler(app)
    update = _build_group_update("/stop")

    assert asyncio.run(handler.check(update)) is True
    result = asyncio.run(handler.handle(update))

    assert result is not None
    assert result.text == "Завершаю игру."
    app.game_engine.finish_game.assert_awaited_once_with(55)
    app.sender.answer_callback_query.assert_not_awaited()


def test_stop_command_rejected_for_non_host() -> None:
    app = SimpleNamespace(
        config=SimpleNamespace(PREFIX="/"),
        market=SimpleNamespace(
            game=SimpleNamespace(
                get_by_chat_id=AsyncMock(
                    return_value=SimpleNamespace(id=55, host_id=5001)
                )
            )
        ),
        users=SimpleNamespace(
            user=SimpleNamespace(
                get_by_external=AsyncMock(return_value=SimpleNamespace(id=4001))
            )
        ),
        sender=SimpleNamespace(answer_callback_query=AsyncMock()),
        game_engine=SimpleNamespace(finish_game=AsyncMock()),
    )
    handler = EndGameHandler(app)
    update = _build_group_update("/stop")

    result = asyncio.run(handler.handle(update))

    assert result is not None
    assert result.text == "Только хост может завершить игру."
    app.game_engine.finish_game.assert_not_awaited()
