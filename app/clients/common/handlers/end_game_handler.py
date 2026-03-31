from app.clients.common.handlers.base import BaseHandler
from app.clients.common.mailbox import MessagePayload, MessageType, Update


class EndGameHandler(BaseHandler):
    async def check(self, update: Update) -> bool:
        if update.from_user is None:
            return False
        if update.type == MessageType.CALLBACK_QUERY:
            return update.callback_query.data == "end_game"
        if update.type == MessageType.TEXT:
            command = self.command_name(update.text)
            return command in {"stop", "end_game"}
        return False

    async def handle(self, update: Update) -> MessagePayload | None:
        is_callback = update.type == MessageType.CALLBACK_QUERY
        game = await self.app.market.game.get_by_chat_id(
            update.chat_id,
            platform=(update.source_platform or "TG"),
        )
        if not game:
            if is_callback:
                await self.app.sender.answer_callback_query(
                    callback_query_id=update.callback_query.id,
                    text="Игра не найдена.",
                    show_alert=True,
                )
                return None
            return MessagePayload(chat_id=update.chat_id, text="Игра не найдена.")

        source_platform = (update.source_platform or "TG").upper()
        actor_user = await self.app.users.user.get_by_external(
            source_platform, update.from_user.id
        )
        if actor_user is None or game.host_id != actor_user.id:
            if is_callback:
                await self.app.sender.answer_callback_query(
                    callback_query_id=update.callback_query.id,
                    text="Только хост может завершить игру.",
                    show_alert=True,
                )
                return None
            return MessagePayload(
                chat_id=update.chat_id, text="Только хост может завершить игру."
            )

        if is_callback:
            await self.app.sender.answer_callback_query(
                callback_query_id=update.callback_query.id,
                text="Завершаю игру.",
            )
        await self.app.game_engine.finish_game(game.id)
        if is_callback:
            return None
        return MessagePayload(chat_id=update.chat_id, text="Завершаю игру.")
