from typing import Optional

from app.clients.common.handlers.base import BaseHandler
from app.clients.common.mailbox import MessagePayload, MessageType, Update
from app.utils.trading import TradeError, leave_active_game


class LeaveGameHandler(BaseHandler):
    _RESETTABLE_ERRORS = {
        "У тебя нет активной игры.",
        "Активная игра не найдена.",
    }

    async def check(self, update: Update) -> bool:
        if update.type != MessageType.TEXT or not update.from_user or not update.message:
            return False
        command = self.command_name(update.text)
        return command in {"leave", "выйти"}

    async def handle(self, update: Update) -> Optional[MessagePayload]:
        source_platform = (update.source_platform or "TG").upper()
        try:
            result = await leave_active_game(self.app, update.from_user.id, platform=source_platform)
            lines = [
                "Ты покинул игру.",
                f"Итоговый капитал: {result['total_capital']}",
            ]
            if result.get("game_finished"):
                lines.append(
                    "Игра автоматически завершена: "
                    f"активных игроков осталось {result['active_players_left']}, минимум {result['min_players']}."
                )
            return MessagePayload(
                chat_id=update.chat_id,
                text="\n".join(lines),
            )
        except TradeError as exc:
            error_text = str(exc)
            if error_text not in self._RESETTABLE_ERRORS:
                return MessagePayload(chat_id=update.chat_id, text=error_text)

            user = await self.app.users.user.get_by_external(source_platform, update.from_user.id)
            active_player = None
            if user is not None:
                active_player = await self.app.users.player.get_active_by_user(user.id)
            if active_player is not None:
                return MessagePayload(chat_id=update.chat_id, text=error_text)

            state = await self.app.fsm.get_state(update.from_user.id, platform=source_platform)
            state_name = str(state[0]).strip().lower() if state and state[0] is not None else ""
            idle_state = str(self.app.fsm.FSM.IDLE)
            if state_name and state_name != idle_state:
                await self.app.fsm.set_state(
                    update.from_user.id,
                    self.app.fsm.FSM.IDLE,
                    platform=source_platform,
                )
                return MessagePayload(
                    chat_id=update.chat_id,
                    text=(
                        "Активная игра не найдена.\n"
                        f"Состояние `{state_name}` сброшено в `{idle_state}`."
                    ),
                )
            return MessagePayload(chat_id=update.chat_id, text=error_text)
