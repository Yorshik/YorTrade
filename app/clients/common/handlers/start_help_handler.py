from __future__ import annotations

from app.clients.common.handlers.base import BaseHandler
from app.clients.common.mailbox import MessagePayload, MessageType, Update
from app.utils.texts import load_text


class StartHelpHandler(BaseHandler):
    async def check(self, update: Update) -> bool:
        if update.type != MessageType.TEXT or not update.message:
            return False
        command = self.command_name(update.text)
        return command in {"start", "help"}

    async def handle(self, update: Update) -> MessagePayload | None:
        help_text = load_text("help", fallback_key="greeting")
        return MessagePayload(chat_id=update.chat_id, text=help_text)
