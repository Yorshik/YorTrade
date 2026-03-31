import logging

from app.clients.common.handlers.base import BaseHandler
from app.clients.common.mailbox import MessagePayload, MessageType, Update
from app.market.models import GameStatus
from app.utils.game_setup import initialize_game_market
from app.utils.lobby import normalize_game_settings

logger = logging.getLogger(__name__)


class BeginGameHandler(BaseHandler):
    def _min_players(self) -> int:
        return max(1, int(self.app.config.MIN_PLAYERS))

    async def _has_enough_players(self, chat_id: int, platform: str) -> bool:
        game = await self.app.market.game.get_by_chat_id(chat_id, platform=platform)
        if not game:
            return False
        players = await self.app.users.player.list_by_game(game.id)
        return len(players) >= self._min_players()

    async def check_command(self, update):
        command = self.command_name(update.text)
        logger.debug("BeginGameHandler command=%s", command)
        if command != "begin_game":
            return False
        source_platform = (update.source_platform or "TG").upper()
        user_state = await self.app.fsm.get_state(
            update.from_user.id, platform=source_platform
        )
        if user_state and user_state[0] not in {
            self.app.fsm.FSM.IN_LOBBY,
            self.app.fsm.FSM.GAME_SETTINGS,
        }:
            logger.debug("BeginGameHandler rejected by state=%s", user_state[0])
            return False
        return True

    async def check_callback(self, update):
        if update.callback_query.data != "begin_game":
            return False
        source_platform = (update.source_platform or "TG").upper()
        user_state = await self.app.fsm.get_state(
            update.from_user.id, platform=source_platform
        )
        logger.debug(
            "BeginGameHandler callback state=%s", user_state[0] if user_state else None
        )
        if user_state and user_state[0] == self.app.fsm.FSM.IDLE:
            await self.app.sender.answer_callback_query(
                callback_query_id=update.callback_query.id,
                text="ты не в лобби",
                show_alert=True,
            )
            return False
        elif user_state and user_state[0] in {
            self.app.fsm.FSM.IN_LOBBY,
            self.app.fsm.FSM.GAME_SETTINGS,
        }:
            game = await self.app.market.game.get_by_chat_id(
                update.chat_id, platform=source_platform
            )
            if not game:
                return False
            if not await self._is_host(game, update):
                await self.app.sender.answer_callback_query(
                    callback_query_id=update.callback_query.id,
                    text="только хост может запустить игру",
                    show_alert=True,
                )
                return False
            if not await self._has_enough_players(update.chat_id, source_platform):
                min_players = self._min_players()
                await self.app.sender.answer_callback_query(
                    callback_query_id=update.callback_query.id,
                    text=f"нужно минимум {min_players} игрок(а/ов), чтобы начать игру",
                    show_alert=True,
                )
                return False
        else:
            return False
        return True

    async def check(self, update: Update):
        if not update.from_user:
            return False
        if update.type == MessageType.TEXT:
            res = await self.check_command(update)
        elif update.type == MessageType.CALLBACK_QUERY:
            res = await self.check_callback(update)
        else:
            return False
        if not res:
            return False
        game = await self.app.market.game.get_by_chat_id(
            update.chat_id,
            platform=(update.source_platform or "TG"),
        )
        logger.debug("BeginGameHandler game found=%s", bool(game))
        if not game:
            return False
        return await self._is_host(game, update)

    async def _is_host(self, game, update: Update) -> bool:
        source_platform = (update.source_platform or "TG").upper()
        actor_user = await self.app.users.user.get_by_external(
            source_platform, update.from_user.id
        )
        if actor_user is None:
            return False
        return game.host_id == actor_user.id

    async def handle(self, update: Update) -> MessagePayload | None:
        game = await self.app.market.game.get_by_chat_id(
            update.chat_id,
            platform=(update.source_platform or "TG"),
        )
        if not game:
            return MessagePayload(chat_id=update.chat_id, text="Игра не найдена.")

        settings = normalize_game_settings(game.settings)
        players = await self.app.users.player.list_by_game(game.id)
        min_players = self._min_players()
        if len(players) < min_players:
            return MessagePayload(
                chat_id=update.chat_id,
                text=f"Нужно минимум {min_players} игрок(а/ов), чтобы начать игру.",
            )

        source_platform = (update.source_platform or "TG").upper()
        host_user = await self.app.users.user.get_by_external(
            source_platform, update.from_user.id
        )
        if host_user is None or not host_user.dm_chat_id:
            return MessagePayload(
                chat_id=update.chat_id,
                text="Хост должен сначала написать боту в личные сообщения.",
            )

        for player in players:
            target_user = await self.app.users.user.get_by_id(player.user_id)
            if target_user is None:
                return MessagePayload(
                    chat_id=update.chat_id,
                    text="Все игроки должны сначала написать боту в личные сообщения.",
                )
            if not target_user.dm_chat_id:
                return MessagePayload(
                    chat_id=update.chat_id,
                    text="Все игроки должны сначала написать боту в личные сообщения.",
                )

        chat_title = None
        if update.message and update.message.chat.title:
            chat_title = update.message.chat.title
        elif (
            update.callback_query
            and update.callback_query.message
            and update.callback_query.message.chat.title
        ):
            chat_title = update.callback_query.message.chat.title

        try:
            await initialize_game_market(self.app, game, chat_title=chat_title)
        except ValueError as exc:
            return MessagePayload(chat_id=update.chat_id, text=str(exc))

        initial_balance = float(settings["default_balance"])
        for player in players:
            player.balance = initial_balance
            await self.app.users.player.save(player)
            target_user = await self.app.users.user.get_by_id(player.user_id)
            if target_user is None:
                continue
            await self.app.fsm.set_state(
                target_user.tg_user_id,
                self.app.fsm.FSM.PLAYING_MAIN,
                {"game_id": game.id},
                platform=target_user.platform,
            )

        game.status = GameStatus.ACTIVE
        game.settings = settings
        await self.app.market.game.save(game)
        await self.app.game_engine.start_game(
            game.id, tick_interval=settings["tick_seconds"]
        )

        return MessagePayload(
            chat_id=update.chat_id,
            text="Игра началась. Рынок запущен.",
        )
