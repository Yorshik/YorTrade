from app.clients.common.handlers.base import BaseHandler
from app.clients.common.mailbox import MessagePayload, MessageType, Update
from app.utils.texts import load_text


class NewChatMemberHandler(BaseHandler):
    async def check(self, update: Update) -> bool:
        if (
            update.type != MessageType.NEW_CHAT_MEMBERS
            or not update.message.new_chat_members
        ):
            return False

        bot_id = int(self.app.config.TG_TOKEN.split(":")[0])
        return any(member.id == bot_id for member in update.message.new_chat_members)

    async def handle(self, update: Update) -> MessagePayload | None:
        greeting_message = load_text("greeting", fallback_key="help")
        return MessagePayload(chat_id=update.chat_id, text=greeting_message)
