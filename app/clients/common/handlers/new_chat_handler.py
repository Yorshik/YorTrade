import json
from pathlib import Path
from typing import Optional

from app.clients.common.handlers.base import BaseHandler
from app.clients.common.mailbox import Update, MessageType, MessagePayload


DATA_DIR = Path(__file__).resolve().parents[4] / "data"
TEXTS_PATH = DATA_DIR / "texts.json"


class NewChatMemberHandler(BaseHandler):
    async def check(self, update: Update) -> bool:
        if update.type != MessageType.NEW_CHAT_MEMBERS or not update.message.new_chat_members:
            return False

        bot_id = int(self.app.config.TG_TOKEN.split(":")[0])
        for member in update.message.new_chat_members:
            if member.id == bot_id:
                return True
        return False

    async def handle(self, update: Update) -> Optional[MessagePayload]:
        with TEXTS_PATH.open(encoding="utf-8") as file:
            greeting_message = json.load(file)["greeting"]
        return MessagePayload(chat_id=update.chat_id, text=greeting_message)
