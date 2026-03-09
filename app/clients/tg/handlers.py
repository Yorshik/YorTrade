import json
import logging
from abc import ABC, abstractmethod
from typing import List, Optional
from aiohttp.web import Application

from app.clients.tg.mailbox import UpdateObject, MessageType
from app.game.engine import GameEngine

logger = logging.getLogger(__name__)


class BaseHandler(ABC):
    def __init__(self, app: Application):
        self.app = app

    @abstractmethod
    def check(self, update: UpdateObject) -> bool:
        raise NotImplementedError

    @abstractmethod
    async def handle(self, update: UpdateObject) -> Optional[str]:
        raise NotImplementedError


class PingHandler(BaseHandler):
    def check(self, update: UpdateObject) -> bool:
        return (
            update.message_type == MessageType.TEXT and
            update.command == "ping"
        )

    async def handle(self, update: UpdateObject) -> Optional[str]:
        return "PONG"


class NewChatMemberHandler(BaseHandler):
    def check(self, update: UpdateObject) -> bool:
        if update.message_type != MessageType.NEW_CHAT_MEMBERS or not update.new_chat_members:
            return False
        
        bot_id = int(self.app["bot_token"].split(":")[0])
        for member in update.new_chat_members:
            if member.get("id") == bot_id:
                return True
        return False

    async def handle(self, update: UpdateObject) -> Optional[str]:
        with open("data/texts.json") as file:
            greeting_message = json.load(file)["greeting"]
        return greeting_message


class StartCycleHandler(BaseHandler):
    def check(self, update: UpdateObject) -> bool:
        return (
            update.message_type == MessageType.TEXT and
            update.command == "start_cycle"
        )

    async def handle(self, update: UpdateObject) -> Optional[str]:
        if not update.data:
            return "Пожалуйста, укажите имя для цикла. Пример: /start_cycle my_game"
        
        cycle_name = update.data.strip()
        engine: GameEngine = self.app["game_engine"]
        
        success = await engine.start_cycle(cycle_name, update.chat_id)
        if success:
            return f"Цикл '{cycle_name}' запущен."
        else:
            return f"Цикл с именем '{cycle_name}' уже запущен."


class StopCycleHandler(BaseHandler):
    def check(self, update: UpdateObject) -> bool:
        return (
            update.message_type == MessageType.TEXT and
            update.command == "stop_cycle"
        )

    async def handle(self, update: UpdateObject) -> Optional[str]:
        if not update.data:
            return "Пожалуйста, укажите имя цикла для остановки. Пример: /stop_cycle my_game"
            
        cycle_name = update.data.strip()
        engine: GameEngine = self.app["game_engine"]
        
        success = await engine.stop_cycle(cycle_name)
        if success:
            return None 
        else:
            return f"Цикл с именем '{cycle_name}' не найден или уже остановлен."


class HandlerFactory:
    def __init__(self, app: Application):
        self.app = app
        self._handlers: List[BaseHandler] = []

    def add_handler(self, handler_class):
        handler_instance = handler_class(self.app)
        self._handlers.append(handler_instance)
        logger.info(f"Хендлер {handler_instance.__class__.__name__} добавлен.")

    async def handle_update(self, update: UpdateObject) -> Optional[str]:
        for handler in self._handlers:
            if handler.check(update):
                return await handler.handle(update)
        return None
