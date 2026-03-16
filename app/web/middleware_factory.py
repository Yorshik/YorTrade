import logging
from typing import TYPE_CHECKING

from app.clients.common.mailbox import MessagePayload, Update
from app.web.middlewares.base import BaseMiddleware, StopProcessing

if TYPE_CHECKING:
    from app.web.application import App

logger = logging.getLogger(__name__)


class MiddlewareFactory:
    def __init__(self, app: App, middlewares):
        self.app = app
        self.middlewares: list[BaseMiddleware] = middlewares

    async def process_update(self, update: Update) -> MessagePayload | None:
        for middleware in self.middlewares:
            try:
                logger.info(
                    "Middleware run update_id=%s middleware=%s",
                    update.update_id,
                    middleware.__class__.__name__,
                )
                response = await middleware.process(update, self.app)
                if isinstance(response, StopProcessing):
                    logger.info(
                        "Middleware stop update_id=%s middleware=%s reason=stop_without_payload",
                        update.update_id,
                        middleware.__class__.__name__,
                    )
                    return None
                if response:
                    logger.info(
                        "Middleware stop update_id=%s middleware=%s reason=payload action=%s chat_id=%s",
                        update.update_id,
                        middleware.__class__.__name__,
                        response.action.value,
                        response.chat_id,
                    )
                    return response
            except Exception as e:
                logger.error(
                    f"Ошибка в мидлвари {middleware.__class__.__name__}: {e}",
                    exc_info=True,
                )
                return MessagePayload(
                    chat_id=update.chat_id,
                    text="Произошла внутренняя ошибка. Попробуйте позже.",
                )
        logger.info("Middleware chain passed update_id=%s", update.update_id)
        return None
