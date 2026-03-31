import logging

from app.clients.common.handlers.base import BaseHandler
from app.clients.common.mailbox import MessagePayload, MessageType, Update

logger = logging.getLogger(__name__)


class PingHandler(BaseHandler):
    async def check(self, update: Update) -> bool:
        if update.type != MessageType.TEXT:
            return False
        command = self.command_name(update.text)
        return command == "ping"

    async def handle(self, update: Update) -> MessagePayload | None:
        logger.info("PingHandler сгенерировал ответ.")
        return MessagePayload(chat_id=update.chat_id, text="ПОНГ")
