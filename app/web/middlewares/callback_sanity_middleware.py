from typing import Optional, TYPE_CHECKING

from app.clients.common.mailbox import MessageType, Update
from app.web.middlewares.base import BaseMiddleware, STOP_PROCESSING
from app.utils.private_ui import show_private_screen

if TYPE_CHECKING:
    from app.web.application import App


class CallbackSanityMiddleware(BaseMiddleware):
    async def process(self, update: Update, app: "App") -> Optional[None]:
        if update.type != MessageType.CALLBACK_QUERY or not update.callback_query or not update.from_user:
            return None

        callback_data = update.callback_query.data or ""
        if not callback_data.startswith("private:"):
            return None

        source_platform = (update.source_platform or "TG").upper()
        if source_platform == "VK":
            return None
        state = await app.fsm.get_state(update.from_user.id, platform=source_platform)
        if not state or not update.callback_query.message:
            return None

        _, data = state
        expected_message_id = data.get("private_message_id")
        current_message_id = update.callback_query.message.message_id
        if expected_message_id in (None, current_message_id):
            return None

        await app.sender.answer_callback_query(
            callback_query_id=update.callback_query.id,
            text="Экран устарел, обновляю.",
            show_alert=False,
        )
        await show_private_screen(
            app,
            update.from_user.id,
            update.chat_id,
            data.get("screen", "main"),
            data,
            expected_message_id,
            target_platform=source_platform,
        )
        return STOP_PROCESSING
