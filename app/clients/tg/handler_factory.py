import importlib
import inspect
import logging
from pathlib import Path
from typing import List, Optional
from aiohttp.web import Application

from app.clients.tg.handlers.base import BaseHandler
from app.clients.tg.mailbox import Update, MessagePayload

logger = logging.getLogger(__name__)


class HandlerFactory:
    def __init__(self, app: Application):
        self.app = app
        self._handlers: List[BaseHandler] = []
        self.discover_handlers()

    def add_handler(self, handler_class):
        handler_instance = handler_class(self.app)
        self._handlers.append(handler_instance)
        logger.info(f"Хендлер {handler_instance.__class__.__name__} добавлен.")

    def discover_handlers(self):
        handlers_dir = Path(__file__).parent / "handlers"
        logger.info(f"Начинаю поиск хендлеров в директории: {handlers_dir}")
        
        for file in handlers_dir.glob("*_handler.py"):
            module_name = f"app.clients.tg.handlers.{file.stem}"
            try:
                module = importlib.import_module(module_name)
                for name, obj in inspect.getmembers(module, inspect.isclass):
                    if issubclass(obj, BaseHandler) and obj is not BaseHandler:
                        self.add_handler(obj)
            except Exception as e:
                logger.error(f"Ошибка при импорте или регистрации хендлера из {file.name}: {e}", exc_info=True)

    async def handle_update(self, update: Update) -> Optional[MessagePayload]:
        logger.info(f"Поиск хендлера для обновления типа {update.type.value}.")
        for handler in self._handlers:
            if handler.check(update):
                logger.info(f"Найден хендлер: {handler.__class__.__name__}.")
                return await handler.handle(update)
        logger.warning("Подходящий хендлер не найден.")
        return None
