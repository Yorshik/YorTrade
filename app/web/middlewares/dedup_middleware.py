from typing import TYPE_CHECKING

from app.clients.common.mailbox import Update
from app.web.middlewares.base import STOP_PROCESSING, BaseMiddleware, StopProcessing

if TYPE_CHECKING:
    from app.web.application import App


class DedupMiddleware(BaseMiddleware):
    TTL_SECONDS = 5

    async def process(self, update: Update, app: App) -> StopProcessing | None:
        dedup_key = f"dedup:update:{(update.source_platform or 'TG').upper()}:{update.update_id}"
        inserted = await app.redis.set_if_absent(
            dedup_key, "1", expires_in=self.TTL_SECONDS
        )
        if inserted:
            return None
        return STOP_PROCESSING
