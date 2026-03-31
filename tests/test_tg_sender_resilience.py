import asyncio
import base64
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.clients.tg.mailbox import MessagePayload
from app.clients.tg.sender import Sender


class _DummySession:
    def post(self, *args, **kwargs):
        return {"args": args, "kwargs": kwargs}


def _build_sender() -> Sender:
    app = SimpleNamespace(
        session=_DummySession(),
        rabbitmq=SimpleNamespace(),
        config=SimpleNamespace(
            TG_API_URL="https://api.telegram.org",
            TG_TOKEN="token",
        ),
    )
    return Sender(app)


def test_edit_message_photo_fallback_resends_and_deletes_old() -> None:
    sender = _build_sender()
    sender._edit_message_media = AsyncMock(return_value=None)
    sender._send_message = AsyncMock(return_value=901)
    sender._delete_message = AsyncMock(return_value=True)

    payload = MessagePayload(
        chat_id=111,
        message_id=700,
        text="caption",
        photo_content_b64=base64.b64encode(b"x").decode("ascii"),
    )

    result = asyncio.run(sender._edit_message(payload))

    assert result == 901
    sender._send_message.assert_awaited_once()
    resend_payload = sender._send_message.await_args.args[0]
    assert resend_payload.message_id is None
    sender._delete_message.assert_awaited_once_with(111, 700)


def test_send_photo_runtime_payload_does_not_fallback_to_text() -> None:
    sender = _build_sender()
    sender._make_request = AsyncMock(return_value=None)
    sender._send_text = AsyncMock(return_value=500)

    payload = MessagePayload(
        chat_id=-1001,
        text="runtime chart",
        photo_content_b64=base64.b64encode(b"x").decode("ascii"),
        runtime_update={"game_id": 1, "message_field": "market_message_id"},
    )

    result = asyncio.run(sender._send_photo(payload))

    assert result is None
    assert sender._make_request.await_count == sender.TRANSPORT_RETRY_COUNT
    sender._send_text.assert_not_awaited()
