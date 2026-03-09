import asyncio
import json
import logging
from typing import Optional

from aio_pika.abc import AbstractIncomingMessage
from aiohttp.web import Application

from app.clients.tg.dto import MessagePayload
from app.clients.tg.mailbox import UpdateObject
from app.store.queue.accessor import RabbitMQAccessor

logger = logging.getLogger(__name__)


class Worker:
    def __init__(self, app: Application):
        self.app = app
        self.rabbitmq: RabbitMQAccessor = self.app["rabbitmq"]
        self.handler_factory = self.app["handler_factory"]
        self._task: Optional[asyncio.Task] = None
        self.updates_queue_name = "telegram_updates"
        self.sender_queue_name = "telegram_sender_queue"

    async def _process_message(self, message: AbstractIncomingMessage):
        async with message.process():
            try:
                update_json = json.loads(message.body.decode('utf-8'))
                update_obj = UpdateObject.from_dict(update_json)
                response_text = await self.handler_factory.handle_update(update_obj)
                if response_text:
                    payload = MessagePayload(
                        chat_id=update_obj.chat_id,
                        text=response_text
                    )
                    await self.rabbitmq.publish(self.sender_queue_name, payload.to_dict())
            except Exception as e:
                logger.error(f"Ошибка обработки сообщения из очереди: {e}", exc_info=True)

    async def _consume(self):
        updates_queue = await self.rabbitmq.get_queue(self.updates_queue_name)
        await updates_queue.consume(self._process_message)
        logger.info(f"Воркер начал прослушивание очереди '{self.updates_queue_name}'.")
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            logger.info("Прослушивание очереди воркером остановлено.")

    async def start(self):
        if not self._task:
            self._task = asyncio.create_task(self._consume())
            logger.info("Воркер запущен.")

    async def stop(self):
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            logger.info("Воркер остановлен.")
