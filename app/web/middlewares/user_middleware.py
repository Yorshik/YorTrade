import logging
from typing import Optional, TYPE_CHECKING

from app.web.middlewares.base import BaseMiddleware
from app.clients.common.mailbox import Update, MessagePayload
from app.utils.platform import normalize_platform

if TYPE_CHECKING:
    from app.web.application import App

logger = logging.getLogger(__name__)


class UserMiddleware(BaseMiddleware):
    async def process(self, update: Update, app: App) -> Optional[MessagePayload]:
        if not update.from_user:
            logger.warning("Не удалось получить данные пользователя из обновления.")
            return None

        platform = normalize_platform(update.source_platform)
        update.source_platform = platform
        tg_user = update.from_user
        user, created_user = await app.users.user.get_or_create(
            platform,
            tg_user.id,
            tg_user.username,
        )
        update.user_id = user.id
        if created_user:
            logger.info("Пользователь %s успешно создан.", tg_user.id)

        if update.message and update.message.chat.type == "private":
            if user.dm_chat_id != update.chat_id:
                await app.users.user.update_private_chat(user, update.chat_id)

        if await app.fsm.get_state(tg_user.id, platform=platform) is None:
            await app.fsm.set_state(tg_user.id, app.fsm.FSM.IDLE, platform=platform)
        return None
