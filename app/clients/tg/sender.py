import asyncio
import aiohttp
import json
import logging
from aiohttp.web import Application
from typing import Optional

from aio_pika.abc import AbstractIncomingMessage
from app.clients.tg.dto import MessagePayload
from app.store.queue.accessor import RabbitMQAccessor

logger = logging.getLogger(__name__)


class Sender:
    def __init__(self, app: Application):
        self.app = app
        self.bot_token = self.app["bot_token"]
        self.session: aiohttp.ClientSession = self.app["session"]
        self.rabbitmq: RabbitMQAccessor = self.app["rabbitmq"]
        self.api_url = f"https://api.telegram.org/bot{self.bot_token}"
        self._task: Optional[asyncio.Task] = None
        self.queue_name = "telegram_sender_queue"

    async def queue_message(self, payload: MessagePayload):
        await self.rabbitmq.publish(self.queue_name, payload.to_dict())

    async def _process_message(self, message: AbstractIncomingMessage):
        async with message.process():
            try:
                payload_json = json.loads(message.body.decode('utf-8'))
                payload = MessagePayload.from_dict(payload_json)
                await self._send_message(payload)
            except Exception as e:
                logger.error(f"Ошибка обработки сообщения для отправки: {e}", exc_info=True)

    async def _consume(self):
        sender_queue = await self.rabbitmq.get_queue(self.queue_name)
        await sender_queue.consume(self._process_message)
        logger.info(f"Сендер начал прослушивание очереди '{self.queue_name}'.")
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            logger.info("Прослушивание очереди сендером остановлено.")

    async def start(self):
        if not self._task:
            self._task = asyncio.create_task(self._consume())
            logger.info("Сендер запущен.")

    async def stop(self):
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            logger.info("Сендер остановлен.")

    async def _send_message(self, payload: MessagePayload) -> Optional[int]:
        if payload.photo_path:
            return await self._send_photo(payload)
        elif payload.text:
            return await self._send_text(payload)
        else:
            logger.warning("Для отправки сообщения нужен хотя бы текст или фото.")
            return None

    async def _send_text(self, payload: MessagePayload) -> Optional[int]:
        url = f"{self.api_url}/sendMessage"
        json_data = {"chat_id": payload.chat_id, "text": payload.text}
        if payload.keyboard:
            json_data["reply_markup"] = payload.keyboard
        
        return await self._make_request(self.session.post(url, json=json_data))

    async def _send_photo(self, payload: MessagePayload) -> Optional[int]:
        url = f"{self.api_url}/sendPhoto"
        data = aiohttp.FormData()
        data.add_field('chat_id', str(payload.chat_id))
        if payload.text:
            data.add_field('caption', payload.text)
        if payload.keyboard:
            data.add_field('reply_markup', json.dumps(payload.keyboard))
        
        try:
            with open(payload.photo_path, 'rb') as photo_file:
                data.add_field('photo', photo_file, filename='photo.jpg', content_type='image/jpeg')
                return await self._make_request(self.session.post(url, data=data))
        except FileNotFoundError:
            logger.error(f"Файл не найден {payload.photo_path}")
            return None
        except Exception as e:
            logger.error(f"Ошибка при подготовке фото: {e}", exc_info=True)
            return None

    async def edit_message(self, payload: MessagePayload) -> Optional[int]:
        url = f"{self.api_url}/editMessageText"
        json_data = {
            "chat_id": payload.chat_id,
            "message_id": payload.message_id,
            "text": payload.text or ""
        }
        if payload.keyboard:
            json_data["reply_markup"] = payload.keyboard

        return await self._make_request(self.session.post(url, json=json_data))

    async def delete_message(self, chat_id: int, message_id: int) -> bool:
        url = f"{self.api_url}/deleteMessage"
        params = {"chat_id": chat_id, "message_id": message_id}
        try:
            async with self.session.post(url, json=params) as response:
                response.raise_for_status()
                data = await response.json()
                return data.get("ok", False)
        except aiohttp.ClientError as e:
            logger.error(f"Ошибка при удалении сообщения: {e}", exc_info=True)
            return False

    async def _make_request(self, request_context) -> Optional[int]:
        try:
            async with request_context as response:
                response.raise_for_status()
                data = await response.json()
                if data.get("ok") and data.get("result"):
                    return data["result"]["message_id"]
                else:
                    logger.error(f"Ошибка от API Telegram: {data.get('description')}")
                    return None
        except aiohttp.ClientError as e:
            logger.error(f"Сетевая ошибка: {e}", exc_info=True)
            return None
        except Exception as e:
            logger.error(f"Неожиданная ошибка при выполнении запроса: {e}", exc_info=True)
            return None
