import logging
from typing import Optional

from app.clients.common.handlers.base import BaseHandler
from app.clients.common.mailbox import Update, MessageType, MessagePayload
from app.market.settings import build_default_game_settings
from app.utils.lobby import render_lobby_keyboard

logger = logging.getLogger(__name__)


class StartGameHandler(BaseHandler):
    async def check(self, update: Update) -> bool:
        if update.type != MessageType.TEXT or not update.message or not update.from_user:
            return False
        command = self.command_name(update.text)
        logger.debug("StartGameHandler command=%s", command)
        if command not in {"start_gameYT", "start_game"}:
            return False
        return True

    async def handle(self, update: Update) -> Optional[MessagePayload]:
        tg_user = update.from_user
        actor_id = tg_user.id
        source_platform = (update.source_platform or "TG").upper()
        user_state = await self.app.fsm.get_state(actor_id, platform=source_platform)
        state_name = str(user_state[0]).strip().lower() if user_state and user_state[0] is not None else ""
        idle_state = str(self.app.fsm.FSM.IDLE)
        if user_state is not None and state_name != idle_state:
            return MessagePayload(
                chat_id=update.chat_id,
                text=f"Нельзя начать новую игру: текущее состояние `{state_name or 'unknown'}`. Сначала заверши/покинь текущую игру.",
            )
        logger.info(f"Пользователь {actor_id} начал новую игру.")
        user = await self.app.users.user.get_by_external(source_platform, tg_user.id)
        if user is None:
            user, _ = await self.app.users.user.get_or_create(source_platform, tg_user.id, tg_user.username)
        if not user.dm_chat_id:
            return MessagePayload(
                chat_id=update.chat_id,
                text="Сначала открой личный чат с ботом, затем запускай игру.",
            )

        game = await self.app.market.game.create_game(
            user.id,
            update.chat_id,
            settings=build_default_game_settings(),
            platform=source_platform,
        )
        await self.app.users.player.get_or_create(
            user.id,
            game.id,
            initial_balance=game.settings["default_balance"],
        )
        await self.app.fsm.set_state(
            actor_id,
            self.app.fsm.FSM.IN_LOBBY,
            {"game_id": game.id},
            platform=source_platform,
        )

        return MessagePayload(
            chat_id=update.chat_id,
            text=(
                f"{update.message.from_user.first_name} начал игру.\n"
                "Лобби создано. Можно присоединяться и менять настройки."
            ),
            keyboard=render_lobby_keyboard(),
        )
