import json
from typing import Optional

from app.clients.tg.handlers.base import BaseHandler
from app.clients.tg.mailbox import Update, MessageType, MessagePayload


class NewChatMemberHandler(BaseHandler):
    def check(self, update: Update) -> bool:
        if update.type != MessageType.NEW_CHAT_MEMBERS or not update.message.new_chat_members:
            return False

        bot_id = int(self.app.config.TG_TOKEN.split(":")[0])
        for member in update.message.new_chat_members:
            if member.id == bot_id:
                return True
        return False

    async def handle(self, update: Update) -> Optional[MessagePayload]:
        with open("data/texts.json") as file:
            greeting_message = json.load(file)["greeting"]
        return MessagePayload(chat_id=update.get_chat_id, text=greeting_message)