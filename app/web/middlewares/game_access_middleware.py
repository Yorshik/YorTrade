from __future__ import annotations

from typing import TYPE_CHECKING

from app.clients.common.mailbox import MessagePayload, MessageType, Update
from app.web.middlewares.base import STOP_PROCESSING, BaseMiddleware

if TYPE_CHECKING:
    from app.web.application import App


class GameAccessMiddleware(BaseMiddleware):
    PRIVATE_COMMANDS = {
        "game",
        "market",
        "buy",
        "sell",
        "portfolio",
        "deals",
        "leaderboard",
        "leave",
        "выйти",
    }

    PLAYING_STATES = {
        "playing_main",
        "playing_asset",
        "playing_buy",
        "playing_sell",
        "playing_portfolio",
        "playing_deals",
        # legacy
        "playing_deal_history",
        "playing_portfolio_asset",
        "playing_price_history",
    }

    async def process(self, update: Update, app: App) -> MessagePayload | None:
        if not update.from_user:
            return None

        source_platform = (update.source_platform or "TG").upper()
        state = await app.fsm.get_state(update.from_user.id, platform=source_platform)
        state_name = state[0] if state else None

        if (
            update.type == MessageType.TEXT
            and update.message
            and update.message.chat.type == "private"
        ):
            command = update.text or ""
            if command.startswith(app.config.PREFIX):
                command = command[1:]
            command_name = command.split()[0] if command else ""
            if command_name not in self.PRIVATE_COMMANDS:
                return None
            if command_name == "leave" and state_name in self.PLAYING_STATES:
                return None
            if state_name in self.PLAYING_STATES:
                return None
            return MessagePayload(
                chat_id=update.chat_id, text="У тебя нет активной игры."
            )

        if update.type == MessageType.CALLBACK_QUERY and update.callback_query:
            callback_data = update.callback_query.data or ""
            if not callback_data.startswith("private:"):
                return None
            if state_name in self.PLAYING_STATES:
                return None
            await app.sender.answer_callback_query(
                callback_query_id=update.callback_query.id,
                text="У тебя нет активной игры.",
                show_alert=True,
            )
            return STOP_PROCESSING

        return None
