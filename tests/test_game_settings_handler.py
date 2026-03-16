import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.clients.common.handlers.game_settings_handler import GameSettingsHandler
from app.clients.common.mailbox import Update


def _build_update(text: str) -> Update:
    return Update.model_validate(
        {
            "update_id": 1,
            "message": {
                "message_id": 10,
                "from": {
                    "id": 12345,
                    "is_bot": False,
                    "first_name": "Tester",
                    "username": "tester",
                },
                "chat": {
                    "id": 777,
                    "type": "private",
                },
                "text": text,
                "new_chat_members": [],
            },
            "source_platform": "TG",
        }
    )


def _build_handler() -> GameSettingsHandler:
    fsm = SimpleNamespace(
        FSM=SimpleNamespace(GAME_SETTINGS="game_settings"),
        get_state=AsyncMock(return_value=("game_settings", {"pending_setting": "tick_seconds"})),
    )
    app = SimpleNamespace(
        config=SimpleNamespace(PREFIX="/"),
        fsm=fsm,
    )
    return GameSettingsHandler(app)


def test_game_settings_check_ignores_bot_commands() -> None:
    handler = _build_handler()
    update = _build_update("/ping")

    result = asyncio.run(handler.check(update))

    assert result is False


def test_game_settings_check_accepts_plain_text_input() -> None:
    handler = _build_handler()
    update = _build_update("60")

    result = asyncio.run(handler.check(update))

    assert result is True
