import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.clients.vk.poller import Poller


def test_vk_poller_resolves_real_user_and_chat_title(monkeypatch) -> None:
    app = SimpleNamespace(
        rabbitmq=SimpleNamespace(),
        session=SimpleNamespace(),
        config=SimpleNamespace(
            VK_API_URL="https://api.vk.com/method",
            VK_TOKEN="token",
            VK_GROUP_ID=123,
            VK_API_VERSION="5.199",
        ),
    )
    poller = Poller(app)
    api_call_mock = AsyncMock(
        side_effect=[
            [{"first_name": "Иван", "last_name": "Петров", "domain": "ivanpetrov"}],
            {
                "items": [
                    {
                        "conversation": {
                            "chat_settings": {
                                "title": "короче тестим йоу",
                            }
                        }
                    }
                ]
            },
        ]
    )
    monkeypatch.setattr(poller, "_api_call", api_call_mock)

    message_new = {
        "type": "message_new",
        "object": {
            "message": {
                "id": 10,
                "peer_id": 2_000_000_001,
                "from_id": 101,
                "text": "ping",
            }
        },
    }
    callback_event = {
        "type": "message_event",
        "object": {
            "peer_id": 2_000_000_001,
            "user_id": 101,
            "event_id": "evt123",
            "conversation_message_id": 99,
            "payload": {"cmd": "group:view_main"},
        },
    }

    normalized_message = asyncio.run(poller._convert_message_new(message_new))
    normalized_callback = asyncio.run(poller._convert_message_event(callback_event))

    assert normalized_message is not None
    assert normalized_message["message"]["from"]["first_name"] == "Иван"
    assert normalized_message["message"]["from"]["last_name"] == "Петров"
    assert normalized_message["message"]["from"]["username"] == "Иван Петров"
    assert normalized_message["message"]["chat"]["title"] == "короче тестим йоу"

    assert normalized_callback is not None
    assert normalized_callback["callback_query"]["from"]["username"] == "Иван Петров"
    assert (
        normalized_callback["callback_query"]["message"]["chat"]["title"]
        == "короче тестим йоу"
    )

    # user/chat profile should come from cache for the second conversion
    assert api_call_mock.await_count == 2
