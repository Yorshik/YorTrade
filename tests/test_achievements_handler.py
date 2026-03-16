import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.clients.common.handlers.achievements_handler import AchievementsHandler
from app.clients.common.mailbox import Update
from app.utils import achievements as achievements_utils


def _build_private_update(
    text: str, *, user_id: int = 12345, platform: str = "TG"
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
                    "id": 777,
                    "type": "private",
                },
                "text": text,
                "new_chat_members": [],
            },
            "source_platform": platform,
        }
    )


def test_achievements_handler_returns_report() -> None:
    stats_row = SimpleNamespace(**achievements_utils.DEFAULT_STATS)
    app = SimpleNamespace(
        config=SimpleNamespace(PREFIX="/"),
        users=SimpleNamespace(
            user=SimpleNamespace(
                get_by_external=AsyncMock(return_value=SimpleNamespace(id=10)),
            ),
            achievement=SimpleNamespace(
                get_or_create=AsyncMock(return_value=stats_row),
            ),
        ),
    )
    handler = AchievementsHandler(app)
    update = _build_private_update("/achievements@testbot")

    assert asyncio.run(handler.check(update)) is True
    result = asyncio.run(handler.handle(update))

    assert result is not None
    assert "Твои достижения" in (result.text or "")


def test_achievements_handler_returns_not_found_message() -> None:
    app = SimpleNamespace(
        config=SimpleNamespace(PREFIX="/"),
        users=SimpleNamespace(
            user=SimpleNamespace(get_by_external=AsyncMock(return_value=None)),
            achievement=SimpleNamespace(get_or_create=AsyncMock()),
        ),
    )
    handler = AchievementsHandler(app)
    update = _build_private_update("/достижения")

    result = asyncio.run(handler.handle(update))

    assert result is not None
    assert "Пользователь не найден" in (result.text or "")
    app.users.achievement.get_or_create.assert_not_awaited()
