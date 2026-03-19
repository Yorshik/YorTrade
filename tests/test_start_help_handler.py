import asyncio
from types import SimpleNamespace

from app.clients.common.handlers.start_help_handler import StartHelpHandler
from app.clients.common.mailbox import Update


def _build_update(text: str) -> Update:
    return Update.model_validate(
        {
            "update_id": 100,
            "message": {
                "message_id": 10,
                "from": {
                    "id": 123,
                    "is_bot": False,
                    "first_name": "Tester",
                    "username": "tester",
                },
                "chat": {"id": 777, "type": "private"},
                "text": text,
                "new_chat_members": [],
            },
            "source_platform": "TG",
        }
    )


def test_start_help_handler_matches_start_and_help() -> None:
    app = SimpleNamespace(config=SimpleNamespace(PREFIX="/"))
    handler = StartHelpHandler(app)

    assert asyncio.run(handler.check(_build_update("/start"))) is True
    assert asyncio.run(handler.check(_build_update("/help"))) is True
    assert asyncio.run(handler.check(_build_update("/ping"))) is False


def test_start_help_handler_returns_text_from_catalog(monkeypatch) -> None:
    app = SimpleNamespace(config=SimpleNamespace(PREFIX="/"))
    handler = StartHelpHandler(app)
    update = _build_update("/help")
    monkeypatch.setattr(
        "app.clients.common.handlers.start_help_handler.load_text",
        lambda *_args, **_kwargs: "Справка бота",
    )

    payload = asyncio.run(handler.handle(update))

    assert payload is not None
    assert payload.chat_id == 777
    assert payload.text == "Справка бота"
