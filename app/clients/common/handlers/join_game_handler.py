import logging
from typing import Optional

from app.clients.common.handlers.base import BaseHandler
from app.clients.common.mailbox import Update, MessagePayload, MessageType

logger = logging.getLogger(__name__)


class JoinGameHandler(BaseHandler):
    async def check_command(self, update: Update):
        if not update.from_user:
            return False
        command = self.command_name(update.text)
        logger.debug("JoinGameHandler command=%s", command)
        if command not in {"join_gameYT", "join_game"}:
            return False
        source_platform = (update.source_platform or "TG").upper()
        user_state = await self.app.fsm.get_state(update.from_user.id, platform=source_platform)
        if user_state and user_state[0] != self.app.fsm.FSM.IDLE:
            logger.debug("JoinGameHandler rejected: user already in state=%s", user_state[0])
            return False
        return True

    async def check_callback(self, update: Update) -> bool:
        if update.callback_query.data != "join_game":
            return False
        if not update.from_user:
            return False
        source_platform = (update.source_platform or "TG").upper()
        user_state = await self.app.fsm.get_state(update.from_user.id, platform=source_platform)
        if user_state and user_state[0] != self.app.fsm.FSM.IDLE:
            await self.app.sender.answer_callback_query(
                callback_query_id=update.callback_query.id,
                text="ты уже присоединился(-лась)",
                show_alert=True
            )
            return False
        return True

    async def check(self, update: Update) -> bool:
        if update.type == MessageType.TEXT:
            return await self.check_command(update)
        if update.type == MessageType.CALLBACK_QUERY:
            return await self.check_callback(update)
        return False

    async def handle(self, update: Update) -> Optional[MessagePayload]:
        tg_user = update.from_user
        name = tg_user.first_name
        source_platform = (update.source_platform or "TG").upper()

        game = await self.app.market.game.get_by_chat_id(update.chat_id, platform=source_platform)
        if not game:
            return MessagePayload(chat_id=update.chat_id, text="Активная игра не найдена.")

        user = await self.app.users.user.get_by_external(source_platform, tg_user.id)
        if user is None:
            user, _ = await self.app.users.user.get_or_create(source_platform, tg_user.id, tg_user.username)

        if not user.dm_chat_id:
            if update.type == MessageType.CALLBACK_QUERY:
                await self.app.sender.answer_callback_query(
                    callback_query_id=update.callback_query.id,
                    text="Сначала напиши боту в личку.",
                    show_alert=True,
                )
            return MessagePayload(
                chat_id=update.chat_id,
                text="Сначала напиши боту в личные сообщения, потом присоединяйся к игре.",
            )

        await self.app.users.player.get_or_create(
            user.id,
            game.id,
            initial_balance=(game.settings or {}).get("default_balance", 1000.0),
        )
        await self.app.fsm.set_state(
            tg_user.id,
            self.app.fsm.FSM.IN_LOBBY,
            {"game_id": game.id},
            platform=source_platform,
        )

        return MessagePayload(
            chat_id=update.chat_id,
            text=(
                f"{name} присоединился к игре!\n"
                f"Платформа: {source_platform}"
            ),
        )
