import asyncio
import logging
from typing import Optional

import aiohttp

from app.store.queue.accessor import RabbitMQAccessor

logger = logging.getLogger(__name__)


class Poller:
    def __init__(self, app):
        self.app = app
        self.rabbitmq: RabbitMQAccessor = self.app.rabbitmq
        self.session: aiohttp.ClientSession = self.app.session
        self.bot_token = self.app.config.TG_TOKEN
        
        self.api_url = f"https://api.telegram.org/bot{self.bot_token}"
        self._running = False
        self._task: Optional[asyncio.Task] = None

    async def _get_updates(self, offset: int, timeout: int = 60) -> Optional[dict]:
        url = f"{self.api_url}/getUpdates"
        params = {"offset": offset, "timeout": timeout, "allowed_updates": ["message", "callback_query"]}
        try:
            async with self.session.get(url, params=params, timeout=timeout + 5) as response:
                response.raise_for_status()
                return await response.json()
        except aiohttp.ClientError as e:
            logger.error(f"Сетевая ошибка при получении обновлений: {e}", exc_info=True)
        except asyncio.TimeoutError:
            logger.warning("Тайм-аут при получении обновлений.")
        except Exception as e:
            logger.error(f"Неизвестная ошибка в _get_updates: {e}", exc_info=True)
        return None

    async def _poll(self):
        offset = 0
        updates_queue_name = "telegram_updates"
        logger.info("Poller начал опрос Telegram API.")
        while self._running:
            updates_response = await self._get_updates(offset)
            if updates_response and updates_response.get("ok") and updates_response.get("result"):
                logger.info(f"Получено {len(updates_response['result'])} обновлений.")
                for update in updates_response["result"]:
                    offset = update["update_id"] + 1
                    logger.info(f"Отправка обновления {update['update_id']} в очередь.")
                    await self.rabbitmq.publish(updates_queue_name, update)
            else:
                await asyncio.sleep(1)

    async def start(self):
        if not self._running:
            self._running = True
            self._task = asyncio.create_task(self._poll())
            logger.info("Poller запущен.")

    async def stop(self):
        if self._running:
            self._running = False
            if self._task:
                self._task.cancel()
                try:
                    await self._task
                except asyncio.CancelledError:
                    pass
            logger.info("Poller остановлен.")
