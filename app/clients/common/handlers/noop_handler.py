from typing import Optional

from app.clients.common.handlers.base import BaseHandler
from app.clients.common.mailbox import MessagePayload, MessageType, Update


class NoopHandler(BaseHandler):
    async def check(self, update: Update) -> bool:
        return update.type == MessageType.CALLBACK_QUERY and update.callback_query.data == "noop"

    async def handle(self, update: Update) -> Optional[MessagePayload]:
        await self.app.sender.answer_callback_query(
            callback_query_id=update.callback_query.id,
            text="",
        )
        return None
