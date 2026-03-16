import importlib
import inspect
import logging
from pathlib import Path

from aiohttp.web import Application

from app.clients.common.handlers.base import BaseHandler
from app.clients.common.mailbox import MessagePayload, Update

logger = logging.getLogger(__name__)


class HandlerFactory:
    def __init__(self, app: Application):
        self.app = app
        self._handlers: list[BaseHandler] = []
        self.discover_handlers()

    def add_handler(self, handler_class):
        handler_instance = handler_class(self.app)
        self._handlers.append(handler_instance)
        logger.debug("Handler registered: %s", handler_instance.__class__.__name__)

    def discover_handlers(self):
        handlers_dir = Path(__file__).parent / "handlers"
        logger.info("Discovering handlers in %s", handlers_dir)

        for file in handlers_dir.glob("*_handler.py"):
            module_name = f"app.clients.common.handlers.{file.stem}"
            try:
                module = importlib.import_module(module_name)
                for _, obj in inspect.getmembers(module, inspect.isclass):
                    if issubclass(obj, BaseHandler) and obj is not BaseHandler:
                        self.add_handler(obj)
            except Exception as error:
                logger.error(
                    "Ошибка при импорте/регистрации хендлера %s: %s",
                    file.name,
                    error,
                    exc_info=True,
                )

    async def handle_update(self, update: Update) -> MessagePayload | None:
        logger.info(
            "Handler search update_id=%s type=%s chat_id=%s from_user=%s",
            update.update_id,
            update.type.value,
            update.chat_id,
            update.from_user.id if update.from_user else None,
        )
        for handler in self._handlers:
            if await handler.check(update):
                logger.info(
                    "Handler matched update_id=%s type=%s handler=%s",
                    update.update_id,
                    update.type.value,
                    handler.__class__.__name__,
                )
                return await handler.handle(update)
        logger.info(
            "No handler matched update_id=%s type=%s text=%s callback=%s",
            update.update_id,
            update.type.value,
            (update.text or "")[:120],
            (update.callback_query.data if update.callback_query else "")[:120],
        )
        return None
