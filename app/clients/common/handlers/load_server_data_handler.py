import logging

from app.clients.common.handlers.base import BaseHandler
from app.clients.common.mailbox import MessagePayload, MessageType, Update
from app.utils.data_loader import load_server_data

logger = logging.Logger(__name__)


class LoadServerDataHandler(BaseHandler):
    async def check(self, update: Update) -> bool:
        if update.type != MessageType.TEXT or not update.from_user:
            return False
        command = self.command_name(update.text)
        if command != "load_server_data":
            return False
        logger.info(f"Команда: {command}, {self.app.config.ADMIN_TG_ID}")
        return update.from_user.id == self.app.config.ADMIN_TG_ID

    async def handle(self, update: Update) -> MessagePayload | None:
        stats = await load_server_data(self.app)
        return MessagePayload(
            chat_id=update.chat_id,
            text=(
                "Данные загружены.\n"
                f"Создано активов: {stats['assets_created']}\n"
                f"Создано фраз: {stats['phrases_created']}"
            ),
        )
