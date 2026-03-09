import json
import logging
from typing import Optional, Dict

import aio_pika
from aio_pika.abc import AbstractRobustConnection, AbstractRobustChannel, AbstractQueue

logger = logging.getLogger(__name__)


class RabbitMQAccessor:
    def __init__(self, dsn: str):
        self.dsn = dsn
        self.connection: Optional[AbstractRobustConnection] = None
        self.channel: Optional[AbstractRobustChannel] = None
        self.queues: Dict[str, AbstractQueue] = {}

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
                raise ConnectionError("Канал RabbitMQ не инициализирован. Вызовите connect() перед получением очереди.")
            self.queues[queue_name] = await self.channel.declare_queue(queue_name, durable=durable)
        return self.queues[queue_name]

    async def publish(self, queue_name: str, message: dict):
        if not self.channel:
            logger.error("Ошибка: нет активного канала для публикации.")
            return
        
        await self.get_queue(queue_name)
        
        body = json.dumps(message).encode('utf-8')
        await self.channel.default_exchange.publish(
            aio_pika.Message(
                body=body,
                delivery_mode=aio_pika.DeliveryMode.PERSISTENT
            ),
            routing_key=queue_name,
        )
