from typing import Optional, TYPE_CHECKING

from app.clients.common.mailbox import MessagePayload, MessageType, Update
from app.web.middlewares.base import BaseMiddleware, STOP_PROCESSING

if TYPE_CHECKING:
    from app.web.application import App


class MaintenanceMiddleware(BaseMiddleware):
    KEY = "maintenance_mode"

    async def process(self, update: Update, app: "App") -> Optional[MessagePayload]:
        if not update.chat_id:
            return None
        if update.type == MessageType.CALLBACK_QUERY and update.callback_query:
            if await app.redis.get(self.KEY):
                await app.sender.answer_callback_query(
                    callback_query_id=update.callback_query.id,
                    text="Бот временно на обслуживании.",
                    show_alert=True,
                )
                return STOP_PROCESSING
            return None

        if await app.redis.get(self.KEY):
            return MessagePayload(
                chat_id=update.chat_id,
                text="Бот временно на обслуживании. Попробуйте позже.",
            )
        return None
