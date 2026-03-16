import logging
from typing import Optional

from app.clients.common.handlers.base import BaseHandler
from app.clients.common.mailbox import Update, MessageType, MessagePayload

logger = logging.getLogger(__name__)


class PingHandler(BaseHandler):
    async def check(self, update: Update) -> bool:
        if update.type != MessageType.TEXT:
            return False
        command = self.command_name(update.text)
        return command == "ping"

    async def handle(self, update: Update) -> Optional[MessagePayload]:
        logger.info("PingHandler сгенерировал ответ.")
        return MessagePayload(chat_id=update.chat_id, text="PONG")
