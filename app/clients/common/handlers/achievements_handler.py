from app.clients.common.handlers.base import BaseHandler
from app.clients.common.mailbox import MessagePayload, MessageType, Update
from app.utils.achievements import build_achievements_report


class AchievementsHandler(BaseHandler):
    COMMANDS = {"achievements", "достижения"}

    async def check(self, update: Update) -> bool:
        if (
            update.type != MessageType.TEXT
            or not update.from_user
            or not update.message
        ):
            return False
        if update.message.chat.type != "private":
            return False
        return self.command_name(update.text) in self.COMMANDS

    async def handle(self, update: Update) -> MessagePayload | None:
        source_platform = (update.source_platform or "TG").upper()
        user = await self.app.users.user.get_by_external(
            source_platform, update.from_user.id
        )
        if user is None:
            return MessagePayload(
                chat_id=update.chat_id,
                text="Пользователь не найден. Напиши любое сообщение боту в личку и попробуй снова.",
            )

        stats = await self.app.users.achievement.get_or_create(user.id)
        return MessagePayload(
            chat_id=update.chat_id,
            text=build_achievements_report(stats),
        )
