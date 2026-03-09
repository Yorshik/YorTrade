import asyncio
import logging
from typing import Dict
from aiohttp.web import Application

from app.clients.tg.dto import MessagePayload
from app.clients.tg.sender import Sender

logger = logging.getLogger(__name__)


class GameEngine:
    def __init__(self, app: Application):
        self.app = app
        self.sender: Sender = self.app["sender"]
        self._running_cycles: Dict[str, asyncio.Task] = {}

    async def _cycle_task(self, name: str, chat_id: int):
        i = 0
        try:
            while True:
                i += 1
                payload = MessagePayload(
                    chat_id=chat_id,
                    text=f"Цикл '{name}', итерация: {i}"
                )
                await self.sender.queue_message(payload)
                await asyncio.sleep(10)
        except asyncio.CancelledError:
            logger.info(f"Цикл '{name}' был остановлен.")
            payload = MessagePayload(
                chat_id=chat_id,
                text=f"Цикл '{name}' успешно остановлен."
            )
            asyncio.create_task(self.sender.queue_message(payload))

    async def start_cycle(self, name: str, chat_id: int) -> bool:
        if name in self._running_cycles and not self._running_cycles[name].done():
            logger.warning(f"Цикл с именем '{name}' уже запущен.")
            return False

        task = asyncio.create_task(self._cycle_task(name, chat_id))
        self._running_cycles[name] = task
        logger.info(f"Цикл '{name}' запущен для чата {chat_id}.")
        return True

    async def stop_cycle(self, name: str) -> bool:
        task = self._running_cycles.get(name)
        if not task or task.done():
            logger.warning(f"Цикл с именем '{name}' не найден или уже завершен.")
            return False

        task.cancel()
        del self._running_cycles[name]
        return True

    async def stop_all_cycles(self):
        logger.info("Остановка всех циклов...")
        for name in list(self._running_cycles.keys()):
            await self.stop_cycle(name)
        logger.info("Все циклы остановлены.")
