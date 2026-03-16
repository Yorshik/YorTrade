import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.clients.common.handlers.leaderboard_handler import LeaderboardHandler
from app.clients.common.mailbox import InlineKeyboardMarkup, MessageType
from app.utils import private_ui, render


def _build_app_for_render() -> SimpleNamespace:
    return SimpleNamespace(
        config=SimpleNamespace(
            TG_BOT_USERNAME="testbot",
            VK_GROUP_ID=0,
        ),
        market=SimpleNamespace(
            game=SimpleNamespace(
                get_by_id=AsyncMock(
                    return_value=SimpleNamespace(settings={"tick_seconds": 10})
                )
            ),
            game_asset=SimpleNamespace(
                list_by_game=AsyncMock(
                    return_value=[
                        SimpleNamespace(
                            asset_id=1, shares_total=1000, shares_available=900
                        ),
                        SimpleNamespace(
                            asset_id=2, shares_total=1000, shares_available=700
                        ),
                    ]
                )
            ),
        ),
        users=SimpleNamespace(
            player=SimpleNamespace(
                list_by_game=AsyncMock(
                    return_value=[SimpleNamespace(id=10, user_id=20, is_active=True)]
                )
            ),
            user=SimpleNamespace(
                get_by_id=AsyncMock(
                    return_value=SimpleNamespace(id=20, platform="TG", dm_chat_id=777)
                )
            ),
        ),
        sender=SimpleNamespace(
            send_message=AsyncMock(),
            edit_message=AsyncMock(),
            delete_message=AsyncMock(),
        ),
    )


def test_refresh_market_message_recreates_large_message_when_generated(
    monkeypatch,
) -> None:
    app = _build_app_for_render()
    monkeypatch.setattr(
        render,
        "build_leaderboard",
        AsyncMock(
            return_value=[{"player_id": 10, "display_name": "u", "capital": 1500.0}]
        ),
    )
    monkeypatch.setattr(
        render, "generate_market_overview_chart", lambda *_: "chart_b64"
    )
    monkeypatch.setattr(render, "save_runtime_state", AsyncMock())

    state = {
        "game_id": 1,
        "chat_id": -1001,
        "platform": "TG",
        "chat_title": "Main Chat",
        "tick": 4,
        "ends_at": None,
        "status": "running",
        "market_view": "main",
        "assets": {
            "1": {
                "asset_id": 1,
                "name": "Alpha",
                "current_price": 10.0,
                "history": [9.0, 10.0],
            },
            "2": {
                "asset_id": 2,
                "name": "Beta",
                "current_price": 20.0,
                "history": [22.0, 20.0],
            },
        },
        "market_message_id": 77,
        "market_message_pending": False,
        "market_message_pending_since": None,
    }

    asyncio.run(
        render.refresh_market_message(
            app,
            game_id=1,
            state=state,
            generated={"news": "breaking"},
        )
    )

    app.sender.delete_message.assert_awaited_once_with(-1001, 77, target_platform="TG")
    assert app.sender.send_message.await_count == 2
    first_payload = app.sender.send_message.await_args_list[0].args[0]
    second_payload = app.sender.send_message.await_args_list[1].args[0]
    assert "Новости:" in (first_payload.text or "")
    assert second_payload.photo_content_b64 == "chart_b64"


def test_refresh_market_message_edits_when_no_generated(monkeypatch) -> None:
    app = _build_app_for_render()
    monkeypatch.setattr(
        render,
        "build_leaderboard",
        AsyncMock(
            return_value=[{"player_id": 10, "display_name": "u", "capital": 1500.0}]
        ),
    )
    monkeypatch.setattr(
        render, "generate_market_overview_chart", lambda *_: "chart_b64"
    )
    monkeypatch.setattr(render, "save_runtime_state", AsyncMock())

    state = {
        "game_id": 1,
        "chat_id": -1001,
        "platform": "TG",
        "chat_title": "Main Chat",
        "tick": 4,
        "ends_at": None,
        "status": "running",
        "market_view": "main",
        "assets": {
            "1": {
                "asset_id": 1,
                "name": "Alpha",
                "current_price": 10.0,
                "history": [9.0, 10.0],
            },
        },
        "market_message_id": 88,
        "market_message_pending": False,
        "market_message_pending_since": None,
    }

    asyncio.run(
        render.refresh_market_message(app, game_id=1, state=state, generated=None)
    )

    app.sender.edit_message.assert_awaited_once()
    app.sender.send_message.assert_not_awaited()
    app.sender.delete_message.assert_not_awaited()


def test_leaderboard_callback_switches_group_view(monkeypatch) -> None:
    runtime_state = {
        "market_view": "main",
        "market_message_pending": True,
        "market_message_pending_since": "2025-01-01T00:00:00+00:00",
    }
    refresh_mock = AsyncMock()
    save_mock = AsyncMock()
    monkeypatch.setattr(
        "app.clients.common.handlers.leaderboard_handler.load_runtime_state",
        AsyncMock(return_value=runtime_state),
    )
    monkeypatch.setattr(
        "app.clients.common.handlers.leaderboard_handler.refresh_market_message",
        refresh_mock,
    )
    monkeypatch.setattr(
        "app.clients.common.handlers.leaderboard_handler.save_runtime_state",
        save_mock,
    )

    app = SimpleNamespace(
        market=SimpleNamespace(
            game=SimpleNamespace(
                get_by_chat_id=AsyncMock(return_value=SimpleNamespace(id=42))
            )
        ),
        sender=SimpleNamespace(answer_callback_query=AsyncMock()),
    )
    handler = LeaderboardHandler(app)
    update = SimpleNamespace(
        type=MessageType.CALLBACK_QUERY,
        chat_id=-1001,
        source_platform="TG",
        from_user=SimpleNamespace(id=10),
        callback_query=SimpleNamespace(
            id="cbq1",
            data="group:view_market",
            message=SimpleNamespace(message_id=501),
        ),
    )

    asyncio.run(handler.handle(update))

    assert runtime_state["market_view"] == "market"
    assert runtime_state["market_message_pending"] is False
    assert runtime_state["market_message_pending_since"] is None
    assert runtime_state["market_message_id"] == 501
    save_mock.assert_awaited_once_with(app, runtime_state)
    refresh_mock.assert_awaited_once_with(app, 42, runtime_state, generated=None)


def test_private_show_private_screen_deletes_previous_message_on_send(
    monkeypatch,
) -> None:
    keyboard = InlineKeyboardMarkup(inline_keyboard=[])
    monkeypatch.setattr(
        private_ui,
        "build_private_screen",
        AsyncMock(
            return_value=(
                "caption",
                keyboard,
                "chart_b64",
                {"game_id": 1},
                "playing_main",
            )
        ),
    )

    app = SimpleNamespace(
        sender=SimpleNamespace(
            send_message=AsyncMock(),
            delete_message=AsyncMock(),
        ),
        fsm=SimpleNamespace(set_state=AsyncMock()),
    )

    asyncio.run(
        private_ui.show_private_screen(
            app,
            tg_user_id=100,
            chat_id=555,
            screen="main",
            data={"game_id": 1, "private_message_id": 321},
            message_id=None,
            target_platform="TG",
        )
    )

    app.sender.send_message.assert_awaited_once()
    app.sender.delete_message.assert_awaited_once_with(555, 321, target_platform="TG")


def test_company_screen_disables_buy_button_during_buyback(monkeypatch) -> None:
    monkeypatch.setattr(
        private_ui,
        "get_active_player_context",
        AsyncMock(
            return_value=(
                SimpleNamespace(id=1),
                SimpleNamespace(id=10),
                SimpleNamespace(id=20),
                {
                    "assets": {
                        "1": {
                            "asset_id": 1,
                            "name": "Alpha",
                            "current_price": 100.0,
                            "active_event": {"type": "buyback", "ticks_left": 3},
                        }
                    }
                },
            )
        ),
    )
    monkeypatch.setattr(private_ui, "generate_asset_price_chart", lambda *_: "chart")
    monkeypatch.setattr(private_ui, "_tick_seconds", AsyncMock(return_value=10))

    app = SimpleNamespace(
        market=SimpleNamespace(
            game_asset=SimpleNamespace(
                get=AsyncMock(return_value=SimpleNamespace(shares_available=1000))
            ),
            portfolio=SimpleNamespace(
                get_or_create=AsyncMock(return_value=SimpleNamespace(amount=5))
            ),
        ),
        fsm=SimpleNamespace(FSM=SimpleNamespace(PLAYING_ASSET="playing_asset")),
    )

    _, keyboard, _, _, _ = asyncio.run(
        private_ui._build_company_screen(app, tg_user_id=777, data={"asset_id": 1})
    )

    buy_button = keyboard.inline_keyboard[0][0]
    assert buy_button.text == "❌ Купить"
    assert buy_button.callback_data == "noop"


def test_company_screen_keeps_buy_button_for_regular_state(monkeypatch) -> None:
    monkeypatch.setattr(
        private_ui,
        "get_active_player_context",
        AsyncMock(
            return_value=(
                SimpleNamespace(id=1),
                SimpleNamespace(id=10),
                SimpleNamespace(id=20),
                {
                    "assets": {
                        "1": {
                            "asset_id": 1,
                            "name": "Alpha",
                            "current_price": 100.0,
                            "active_event": None,
                        }
                    }
                },
            )
        ),
    )
    monkeypatch.setattr(private_ui, "generate_asset_price_chart", lambda *_: "chart")
    monkeypatch.setattr(private_ui, "_tick_seconds", AsyncMock(return_value=10))

    app = SimpleNamespace(
        market=SimpleNamespace(
            game_asset=SimpleNamespace(
                get=AsyncMock(return_value=SimpleNamespace(shares_available=1000))
            ),
            portfolio=SimpleNamespace(
                get_or_create=AsyncMock(return_value=SimpleNamespace(amount=5))
            ),
        ),
        fsm=SimpleNamespace(FSM=SimpleNamespace(PLAYING_ASSET="playing_asset")),
    )

    _, keyboard, _, _, _ = asyncio.run(
        private_ui._build_company_screen(app, tg_user_id=777, data={"asset_id": 1})
    )

    buy_button = keyboard.inline_keyboard[0][0]
    assert buy_button.text == "Купить"
    assert buy_button.callback_data == "private:trade_menu:buy:1"
