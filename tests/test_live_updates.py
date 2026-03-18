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


def test_update_dm_feed_upserts_event_by_event_id() -> None:
    state = {"tick": 10}
    generated = {
        "events": [
            {
                "event_id": "evt:10:tpl_1",
                "type": "market_event",
                "template_id": "tpl_1",
                "text": "обвал рынка",
                "ticks_left": 3,
                "include_remaining": True,
            }
        ]
    }

    first_changed = live_updates._update_dm_feed(state, generated)
    assert first_changed is True
    assert len(state["dm_feed"]["events"]) == 1
    assert state["dm_feed"]["events"][0]["active_until"] == 13

    state["tick"] = 11
    generated["events"][0]["ticks_left"] = 2
    second_changed = live_updates._update_dm_feed(state, generated)
    assert second_changed is True
    assert len(state["dm_feed"]["events"]) == 1
    assert state["dm_feed"]["events"][0]["source_tick"] == 11
    assert state["dm_feed"]["events"][0]["active_until"] == 13


def test_update_dm_feed_removes_event_when_ticks_left_zero() -> None:
    state = {"tick": 20}
    generated = {
        "events": [
            {
                "event_id": "evt:20:tpl_1",
                "type": "market_event",
                "template_id": "tpl_1",
                "text": "обвал рынка",
                "ticks_left": 1,
                "include_remaining": True,
            }
        ]
    }

    assert live_updates._update_dm_feed(state, generated) is True
    assert len(state["dm_feed"]["events"]) == 1

    state["tick"] = 21
    generated["events"][0]["ticks_left"] = 0
    assert live_updates._update_dm_feed(state, generated) is True
    assert state["dm_feed"]["events"] == []


def test_update_dm_feed_drops_zero_remaining_events_without_generated() -> None:
    state = {
        "tick": 30,
        "dm_feed": {
            "news": [],
            "events": [
                {
                    "type": "market_event",
                    "text": "обвал рынка",
                    "active_until": 30,
                    "display_until": 31,
                    "event_ticks": 0,
                    "include_remaining": True,
                }
            ],
            "insiders": [],
        },
    }

    assert live_updates._update_dm_feed(state, generated=None) is True
    assert state["dm_feed"]["events"] == []
