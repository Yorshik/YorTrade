from app.clients.common.handlers.base import BaseHandler
from app.clients.common.mailbox import MessagePayload, MessageType, Update
from app.utils.render import (
    GROUP_VIEW_KEY,
    GROUP_VIEW_LEADERBOARD,
    GROUP_VIEW_MAIN,
    GROUP_VIEW_MARKET,
    refresh_market_message,
)
from app.utils.runtime import load_runtime_state, save_runtime_state
from app.utils.trading import TradeError, build_leaderboard, get_active_player_context


class LeaderboardHandler(BaseHandler):
    _GROUP_VIEW_CALLBACKS = {
        "show_leaderboard": GROUP_VIEW_LEADERBOARD,
        "show_market": GROUP_VIEW_MARKET,
        "show_assets": GROUP_VIEW_MARKET,
        "group:view_leaderboard": GROUP_VIEW_LEADERBOARD,
        "group:view_market": GROUP_VIEW_MARKET,
        "group:view_main": GROUP_VIEW_MAIN,
    }

    async def check(self, update: Update) -> bool:
        if not update.from_user:
            return False
        if update.type == MessageType.CALLBACK_QUERY:
            return update.callback_query.data in self._GROUP_VIEW_CALLBACKS
        if (
            update.type == MessageType.TEXT
            and update.message
            and update.message.chat.type == "private"
        ):
            command = self.cut_prefix(update.text)
            return command == "leaderboard"
        return False

    async def handle(self, update: Update) -> MessagePayload | None:
        if update.type == MessageType.CALLBACK_QUERY:
            game = await self.app.market.game.get_by_chat_id(
                update.chat_id,
                platform=(update.source_platform or "TG"),
            )
            if not game:
                await self.app.sender.answer_callback_query(
                    callback_query_id=update.callback_query.id,
                    text="Игра не найдена.",
                    show_alert=True,
                )
                return None

            runtime_state = await load_runtime_state(self.app, game.id)
            if runtime_state is None:
                await self.app.sender.answer_callback_query(
                    callback_query_id=update.callback_query.id,
                    text="Состояние игры не найдено.",
                    show_alert=True,
                )
                return None

            view = self._GROUP_VIEW_CALLBACKS.get(
                update.callback_query.data, GROUP_VIEW_MAIN
            )
            runtime_state[GROUP_VIEW_KEY] = view
            runtime_state["market_message_pending"] = False
            runtime_state["market_message_pending_since"] = None
            callback_message_id = (
                update.callback_query.message.message_id
                if update.callback_query.message
                else None
            )
            if callback_message_id and runtime_state.get("market_message_id") is None:
                runtime_state["market_message_id"] = callback_message_id
            await save_runtime_state(self.app, runtime_state)
            await self.app.sender.answer_callback_query(
                callback_query_id=update.callback_query.id,
                text="Обновляю сообщение.",
            )
            await refresh_market_message(
                self.app, game.id, runtime_state, generated=None
            )
            return None
        else:
            source_platform = (update.source_platform or "TG").upper()
            try:
                _, _, game, _ = await get_active_player_context(
                    self.app,
                    update.from_user.id,
                    platform=source_platform,
                )
            except TradeError as exc:
                return MessagePayload(chat_id=update.chat_id, text=str(exc))
            leaderboard = await build_leaderboard(self.app, game.id)
            runtime_state = await load_runtime_state(self.app, game.id)
            current_tick = int((runtime_state or {}).get("tick", 0))
            is_finished = bool(
                runtime_state and runtime_state.get("status") == "finished"
            )
            players = await self.app.users.player.list_by_game(game.id)
            players_map = {player.id: player for player in players}

        if not leaderboard:
            return MessagePayload(chat_id=update.chat_id, text="Лидерборд пуст.")

        lines = []
        for index, row in enumerate(leaderboard[:20], start=1):
            player = players_map.get(row["player_id"])
            if player is None:
                terminal_label = "не подключен"
            else:
                user = await self.app.users.user.get_by_id(player.user_id)
                if user is None or not user.dm_chat_id:
                    terminal_label = "не подключен"
                else:
                    terminal_label = user.platform
            if player is None:
                status = "пассивен"
            elif is_finished:
                status = "завершил"
            elif not player.is_active:
                status = "вышел"
            elif ((runtime_state or {}).get("last_action_tick") or {}).get(
                str(player.id)
            ) == current_tick - 1:
                status = "активен"
            else:
                status = "пассивен"
            lines.append(
                f"{index}. {row['display_name']} ({float(row['capital']):.2f}$) — {terminal_label} — {status}"
            )
        return MessagePayload(chat_id=update.chat_id, text="\n".join(lines))
