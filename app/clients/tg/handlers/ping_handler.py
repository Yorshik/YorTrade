import logging
from typing import Optional

from app.clients.tg.handlers.base import BaseHandler
from app.clients.tg.mailbox import Update, MessageType, MessagePayload

logger = logging.getLogger(__name__)


class PingHandler(BaseHandler):
    def check(self, update: Update) -> bool:
        return (
            update.type == MessageType.TEXT and
            update.get_text == "/ping"
        )

    async def handle(self, update: Update) -> Optional[MessagePayload]:
        logger.info("PingHandler сгенерировал ответ.")
        return MessagePayload(chat_id=update.get_chat_id, text="PONG")
