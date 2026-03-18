import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.clients.common.handlers.game_settings_handler import GameSettingsHandler
from app.clients.common.mailbox import PayloadAction, Update


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
        get_state=AsyncMock(
            return_value=("game_settings", {"pending_setting": "tick_seconds"})
        ),
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


def test_handle_text_input_auto_returns_to_settings_menu() -> None:
    update = _build_update("120")
    app = SimpleNamespace(
        config=SimpleNamespace(PREFIX="/"),
        fsm=SimpleNamespace(
            FSM=SimpleNamespace(GAME_SETTINGS="game_settings"),
            get_state=AsyncMock(
                return_value=(
                    "game_settings",
                    {"pending_setting": "tick_seconds", "settings_message_id": 321},
                )
            ),
            set_state=AsyncMock(),
        ),
        market=SimpleNamespace(game=SimpleNamespace(save=AsyncMock())),
        sender=SimpleNamespace(delete_message=AsyncMock()),
    )
    handler = GameSettingsHandler(app)
    game = SimpleNamespace(id=42, settings={})

    payload = asyncio.run(handler._handle_text_input(update, game))

    assert payload is not None
    assert payload.action == PayloadAction.EDIT
    assert payload.message_id == 321
    assert "Настройки игры" in (payload.text or "")
    app.fsm.set_state.assert_awaited_once()


def test_handle_text_input_auto_returns_even_without_settings_message_id() -> None:
    update = _build_update("12.5")
    app = SimpleNamespace(
        config=SimpleNamespace(PREFIX="/"),
        fsm=SimpleNamespace(
            FSM=SimpleNamespace(GAME_SETTINGS="game_settings"),
            get_state=AsyncMock(
                return_value=(
                    "game_settings",
                    {"pending_setting": "global_volatility"},
                )
            ),
            set_state=AsyncMock(),
        ),
        market=SimpleNamespace(game=SimpleNamespace(save=AsyncMock())),
        sender=SimpleNamespace(delete_message=AsyncMock()),
    )
    handler = GameSettingsHandler(app)
    game = SimpleNamespace(id=42, settings={})

    payload = asyncio.run(handler._handle_text_input(update, game))

    assert payload is not None
    assert payload.action == PayloadAction.SEND
    assert "Настройки игры" in (payload.text or "")
    app.fsm.set_state.assert_awaited_once()
