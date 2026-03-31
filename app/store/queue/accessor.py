import json
import logging

import aio_pika
from aio_pika.abc import AbstractQueue, AbstractRobustChannel, AbstractRobustConnection

logger = logging.getLogger(__name__)


class RabbitMQAccessor:
    def __init__(self, dsn: str):
        self.dsn = dsn
        self.connection: AbstractRobustConnection | None = None
        self.channel: AbstractRobustChannel | None = None
        self.queues: dict[str, AbstractQueue] = {}

    async def connect(self):
        try:
            self.connection = await aio_pika.connect_robust(self.dsn)
            self.channel = await self.connection.channel()
            logger.info("Успешное подключение к RabbitMQ")
        except Exception as e:
            logger.error(f"Ошибка подключения к RabbitMQ: {e}", exc_info=True)
            raise

    async def disconnect(self):
        if self.channel and not self.channel.is_closed:
            await self.channel.close()
        if self.connection and not self.connection.is_closed:
            await self.connection.close()
        logger.info("Соединение с RabbitMQ закрыто")

    async def get_queue(self, queue_name: str, durable: bool = True) -> AbstractQueue:
        if queue_name not in self.queues:
            if not self.channel:
                raise ConnectionError(
                    "Канал RabbitMQ не инициализирован. Вызовите connect() перед получением очереди."
                )
            self.queues[queue_name] = await self.channel.declare_queue(
                queue_name, durable=durable
            )
        return self.queues[queue_name]

    async def publish(self, queue_name: str, message: dict):
        if not self.channel:
            logger.error("Ошибка: нет активного канала для публикации.")
            return

        await self.get_queue(queue_name)

        body = json.dumps(message).encode("utf-8")
        logger.info(
            "Rabbit publish queue=%s size_bytes=%s update_id=%s action=%s chat_id=%s source_update=%s source_user=%s source_platform=%s",
            queue_name,
            len(body),
            message.get("update_id"),
            message.get("action"),
            message.get("chat_id"),
            message.get("source_update_id"),
            message.get("source_user_id"),
            message.get("source_platform"),
        )
        await self.channel.default_exchange.publish(
            aio_pika.Message(body=body, delivery_mode=aio_pika.DeliveryMode.PERSISTENT),
            routing_key=queue_name,
        )
