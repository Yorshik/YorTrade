from __future__ import annotations

from typing import TYPE_CHECKING

from app.clients.common.mailbox import MessageType, Update
from app.utils.platform import build_actor_key
from app.web.middlewares.base import STOP_PROCESSING, BaseMiddleware, StopProcessing

if TYPE_CHECKING:
    from app.web.application import App


class RateLimitMiddleware(BaseMiddleware):
    DEFAULT_TTL_SECONDS = 1
    TRADE_TTL_SECONDS = 2

    def _normalize_action(self, callback_data: str) -> tuple[str, int]:
        if callback_data.startswith("private:trade_exec:buy:"):
            return "private:trade_exec:buy", self.TRADE_TTL_SECONDS
        if callback_data.startswith("private:trade_exec:sell:"):
            return "private:trade_exec:sell", self.TRADE_TTL_SECONDS
        if callback_data.startswith("private:trade_menu:"):
            return "private:trade_menu", self.DEFAULT_TTL_SECONDS
        if callback_data.startswith("private:company:"):
            return "private:company", self.DEFAULT_TTL_SECONDS
        if callback_data.startswith("private:portfolio_page:"):
            return "private:portfolio_page", self.DEFAULT_TTL_SECONDS
        if callback_data.startswith("private:history_page:"):
            return "private:history_page", self.DEFAULT_TTL_SECONDS
        if callback_data.startswith("private:companies_page:"):
            return "private:companies_page", self.DEFAULT_TTL_SECONDS
        if callback_data.startswith("private:"):
            parts = callback_data.split(":")
            if len(parts) >= 2:
                return f"private:{parts[1]}", self.DEFAULT_TTL_SECONDS
        return callback_data, self.DEFAULT_TTL_SECONDS

    async def process(self, update: Update, app: App) -> StopProcessing | None:
        if (
            update.type != MessageType.CALLBACK_QUERY
            or not update.callback_query
            or not update.from_user
        ):
            return None

        action_key, ttl = self._normalize_action(update.callback_query.data or "")
        actor_key = update.actor_key or build_actor_key(
            update.source_platform, update.from_user.id
        )
        redis_key = f"rate_limit:{actor_key}:{action_key}"
        inserted = await app.redis.set_if_absent(redis_key, "1", expires_in=ttl)
        if inserted:
            return None

        await app.sender.answer_callback_query(
            callback_query_id=update.callback_query.id,
            text="Слишком быстро",
            show_alert=False,
        )
        return STOP_PROCESSING
