import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.clients.common.handlers.join_game_handler import JoinGameHandler
from app.clients.common.handlers.leave_game_handler import LeaveGameHandler
from app.clients.common.handlers.start_game_handler import StartGameHandler
from app.clients.common.mailbox import PayloadAction, Update
from app.market.models import GameStatus
from app.utils.lobby import render_lobby_keyboard


def _build_text_update(text: str) -> Update:
    return Update.model_validate(
        {
            "update_id": 1,
            "message": {
                "message_id": 10,
                "from": {
                    "id": 1001,
                    "is_bot": False,
                    "first_name": "Host",
                    "username": "host",
                },
                "chat": {
                    "id": -777,
                    "type": "group",
                    "title": "короче тестим йоу",
                },
                "text": text,
                "new_chat_members": [],
            },
            "source_platform": "TG",
        }
    )


def test_lobby_keyboard_contains_leave_and_stop_buttons() -> None:
    keyboard = render_lobby_keyboard()
    callback_data = [
        button.callback_data for row in keyboard.inline_keyboard for button in row
    ]
    assert "leave_game" in callback_data
    assert "end_game" in callback_data


def test_start_game_handler_renders_lobby_members() -> None:
    update = _build_text_update("/start_game")
    game = SimpleNamespace(id=7, host_id=1, settings={"default_balance": 1000})
    host_user = SimpleNamespace(
        id=1, dm_chat_id=555, username="Хост", platform="TG", tg_user_id=1001
    )
    app = SimpleNamespace(
        config=SimpleNamespace(PREFIX="/"),
        fsm=SimpleNamespace(
            FSM=SimpleNamespace(IDLE="idle", IN_LOBBY="in_lobby"),
            get_state=AsyncMock(return_value=None),
            set_state=AsyncMock(),
        ),
        users=SimpleNamespace(
            user=SimpleNamespace(
                get_by_external=AsyncMock(return_value=host_user),
                get_by_id=AsyncMock(return_value=host_user),
            ),
            player=SimpleNamespace(
                get_or_create=AsyncMock(),
                list_by_game=AsyncMock(return_value=[SimpleNamespace(id=1, user_id=1)]),
            ),
        ),
        market=SimpleNamespace(
            game=SimpleNamespace(create_game=AsyncMock(return_value=game)),
        ),
    )
    handler = StartGameHandler(app)

    result = asyncio.run(handler.handle(update))

    assert result is not None
    assert "Участники (1):" in (result.text or "")
    assert "1. Хост (хост)" in (result.text or "")
    callback_data = [
        button.callback_data
        for row in result.keyboard.inline_keyboard
        for button in row
    ]
    assert "leave_game" in callback_data
    assert "end_game" in callback_data


def test_join_game_callback_updates_lobby_message() -> None:
    host_user = SimpleNamespace(id=1, username="Хост", platform="TG", tg_user_id=1001)
    player_user = SimpleNamespace(
        id=2, username="Игрок", platform="TG", tg_user_id=2002, dm_chat_id=900
    )
    game = SimpleNamespace(id=7, host_id=1, settings={"default_balance": 1000})
    app = SimpleNamespace(
        fsm=SimpleNamespace(
            FSM=SimpleNamespace(IDLE="idle", IN_LOBBY="in_lobby"),
            set_state=AsyncMock(),
        ),
        sender=SimpleNamespace(answer_callback_query=AsyncMock()),
        market=SimpleNamespace(
            game=SimpleNamespace(get_by_chat_id=AsyncMock(return_value=game)),
        ),
        users=SimpleNamespace(
            user=SimpleNamespace(
                get_by_external=AsyncMock(return_value=player_user),
                get_by_id=AsyncMock(side_effect=[host_user, player_user]),
            ),
            player=SimpleNamespace(
                get_or_create=AsyncMock(),
                list_by_game=AsyncMock(
                    return_value=[
                        SimpleNamespace(id=1, user_id=1),
                        SimpleNamespace(id=2, user_id=2),
                    ]
                ),
            ),
        ),
    )
    handler = JoinGameHandler(app)
    update = Update.model_validate(
        {
            "update_id": 1,
            "callback_query": {
                "id": "cb1",
                "from": {
                    "id": 2002,
                    "is_bot": False,
                    "first_name": "Player",
                    "username": "player",
                },
                "message": {
                    "message_id": 33,
                    "chat": {"id": -777, "type": "group", "title": "короче тестим йоу"},
                    "text": "",
                    "new_chat_members": [],
                },
                "data": "join_game",
            },
            "source_platform": "TG",
        }
    )

    result = asyncio.run(handler.handle(update))

    assert result is not None
    assert result.action == PayloadAction.EDIT
    assert result.message_id == 33
    assert "Участники (2):" in (result.text or "")
    assert "1. Хост (хост)" in (result.text or "")
    assert "2. Игрок" in (result.text or "")


def test_leave_game_callback_removes_player_from_pending_lobby() -> None:
    game = SimpleNamespace(id=7, host_id=1, status=GameStatus.PENDING)
    host_user = SimpleNamespace(id=1, username="Хост", platform="TG", tg_user_id=1001)
    player_user = SimpleNamespace(
        id=2, username="Игрок", platform="TG", tg_user_id=2002
    )
    app = SimpleNamespace(
        fsm=SimpleNamespace(
            FSM=SimpleNamespace(IDLE="idle"),
            set_state=AsyncMock(),
        ),
        sender=SimpleNamespace(answer_callback_query=AsyncMock()),
        market=SimpleNamespace(
            game=SimpleNamespace(get_by_chat_id=AsyncMock(return_value=game)),
        ),
        users=SimpleNamespace(
            user=SimpleNamespace(
                get_by_external=AsyncMock(return_value=player_user),
                get_by_id=AsyncMock(return_value=host_user),
            ),
            player=SimpleNamespace(
                remove_from_game=AsyncMock(return_value=True),
                list_by_game=AsyncMock(return_value=[SimpleNamespace(id=1, user_id=1)]),
            ),
        ),
    )
    handler = LeaveGameHandler(app)
    update = Update.model_validate(
        {
            "update_id": 1,
            "callback_query": {
                "id": "cb2",
                "from": {
                    "id": 2002,
                    "is_bot": False,
                    "first_name": "Player",
                    "username": "player",
                },
                "message": {
                    "message_id": 44,
                    "chat": {"id": -777, "type": "group", "title": "короче тестим йоу"},
                    "text": "",
                    "new_chat_members": [],
                },
                "data": "leave_game",
            },
            "source_platform": "TG",
        }
    )

    result = asyncio.run(handler.handle(update))

    app.users.player.remove_from_game.assert_awaited_once_with(2, 7)
    assert result is not None
    assert result.action == PayloadAction.EDIT
    assert result.message_id == 44
    assert "Участники (1):" in (result.text or "")
    assert "1. Хост (хост)" in (result.text or "")
