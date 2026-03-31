from app.clients.common.handlers.base import BaseHandler
from app.clients.common.mailbox import (
    MessagePayload,
    MessageType,
    PayloadAction,
    Update,
)
from app.market.models import GameStatus
from app.utils.lobby import build_lobby_text, render_lobby_keyboard
from app.utils.trading import TradeError, leave_active_game


class LeaveGameHandler(BaseHandler):
    _RESETTABLE_ERRORS = {
        "У тебя нет активной игры.",
        "Активная игра не найдена.",
    }

    @staticmethod
    def _chat_title(update: Update) -> str | None:
        if update.message and update.message.chat.title:
            return str(update.message.chat.title)
        if (
            update.callback_query
            and update.callback_query.message
            and update.callback_query.message.chat.title
        ):
            return str(update.callback_query.message.chat.title)
        return None

    async def check(self, update: Update) -> bool:
        if not update.from_user:
            return False
        if update.type == MessageType.CALLBACK_QUERY and update.callback_query:
            return update.callback_query.data == "leave_game"
        if update.type != MessageType.TEXT or not update.message:
            return False
        return self.command_name(update.text) in {"leave", "выйти"}

    async def _handle_pending_lobby_leave(
        self,
        update: Update,
        game,
        source_platform: str,
    ) -> MessagePayload | None:
        is_callback = (
            update.type == MessageType.CALLBACK_QUERY
            and update.callback_query is not None
        )
        actor_user = await self.app.users.user.get_by_external(
            source_platform, update.from_user.id
        )
        if actor_user is None:
            text = "Тебя нет в лобби."
            if is_callback:
                await self.app.sender.answer_callback_query(
                    callback_query_id=update.callback_query.id,
                    text=text,
                    show_alert=True,
                )
                return None
            return MessagePayload(chat_id=update.chat_id, text=text)

        if actor_user.id == game.host_id:
            text = "Хост не может покинуть лобби. Нажми «Стоп»."
            if is_callback:
                await self.app.sender.answer_callback_query(
                    callback_query_id=update.callback_query.id,
                    text=text,
                    show_alert=True,
                )
                return None
            return MessagePayload(chat_id=update.chat_id, text=text)

        removed = await self.app.users.player.remove_from_game(actor_user.id, game.id)
        if not removed:
            text = "Тебя нет в лобби."
            if is_callback:
                await self.app.sender.answer_callback_query(
                    callback_query_id=update.callback_query.id,
                    text=text,
                    show_alert=True,
                )
                return None
            return MessagePayload(chat_id=update.chat_id, text=text)

        await self.app.fsm.set_state(
            update.from_user.id,
            self.app.fsm.FSM.IDLE,
            platform=source_platform,
        )
        lobby_text = await build_lobby_text(
            self.app,
            game,
            chat_title=self._chat_title(update),
        )
        if is_callback:
            await self.app.sender.answer_callback_query(
                callback_query_id=update.callback_query.id,
                text="Ты покинул лобби.",
            )
            return MessagePayload(
                chat_id=update.chat_id,
                action=PayloadAction.EDIT,
                message_id=update.callback_query.message.message_id,
                text=lobby_text,
                keyboard=render_lobby_keyboard(),
            )
        return MessagePayload(
            chat_id=update.chat_id, text=lobby_text, keyboard=render_lobby_keyboard()
        )

    async def handle(self, update: Update) -> MessagePayload | None:
        source_platform = (update.source_platform or "TG").upper()
        game = await self.app.market.game.get_by_chat_id(
            update.chat_id, platform=source_platform
        )
        if game and game.status == GameStatus.PENDING:
            return await self._handle_pending_lobby_leave(update, game, source_platform)

        try:
            result = await leave_active_game(
                self.app, update.from_user.id, platform=source_platform
            )
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

            user = await self.app.users.user.get_by_external(
                source_platform, update.from_user.id
            )
            active_player = None
            if user is not None:
                active_player = await self.app.users.player.get_active_by_user(user.id)
            if active_player is not None:
                return MessagePayload(chat_id=update.chat_id, text=error_text)

            state = await self.app.fsm.get_state(
                update.from_user.id, platform=source_platform
            )
            state_name = (
                str(state[0]).strip().lower() if state and state[0] is not None else ""
            )
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
