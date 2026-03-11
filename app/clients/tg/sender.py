import asyncio
import aiohttp
import json
import logging
from typing import Optional

from aio_pika.abc import AbstractIncomingMessage
from app.clients.tg.mailbox import MessagePayload
from app.store.queue.accessor import RabbitMQAccessor

logger = logging.getLogger(__name__)


class RateLimitError(Exception):
    pass


class Sender:
    RETRY_DELAY_SECONDS = 5

    def __init__(self, app):
        self.app = app
        self.session: aiohttp.ClientSession = app.session
        self.rabbitmq: RabbitMQAccessor = app.rabbitmq
        self.api_url = f"{app.config.TG_API_URL}/bot{app.config.TG_TOKEN}"
        self._task: Optional[asyncio.Task] = None
        self.queue_name = "telegram_sender_queue"

    async def _requeue_message(self, payload: MessagePayload):
        payload.retry_count += 1
        delay = self.RETRY_DELAY_SECONDS
        logger.warning(
            f"Превышен лимит запросов. Повторная попытка через {delay} секунд. "
            f"Попытка {payload.retry_count} для чата {payload.chat_id}."
        )
        await asyncio.sleep(delay)
        await self.rabbitmq.publish(self.queue_name, payload.model_dump(mode="json"))

    async def _process_message(self, message: AbstractIncomingMessage):
        async with message.process():
            payload = MessagePayload.model_validate(json.loads(message.body.decode('utf-8')))
            logger.info(f"Сендер получил сообщение из очереди: {payload.model_dump_json()}")
            
            try:
                await self._send_message(payload)
            except RateLimitError:
                await self._requeue_message(payload)
            except Exception as e:
                logger.error(f"Необработанная ошибка при отправке сообщения: {e}", exc_info=True)

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
            json_data["reply_markup"] = payload.keyboard.model_dump(mode="json")
        
        logger.info(f"Отправка текстового сообщения: {json_data}")
        return await self._make_request(self.session.post(url, json=json_data))

    async def _send_photo(self, payload: MessagePayload) -> Optional[int]:
        url = f"{self.api_url}/sendPhoto"
        data = aiohttp.FormData()
        data.add_field('chat_id', str(payload.chat_id))
        if payload.text:
            data.add_field('caption', payload.text)
        if payload.keyboard:
            data.add_field('reply_markup', payload.keyboard.model_dump_json())
        
        try:
            with open(payload.photo_path, 'rb') as photo_file:
                data.add_field('photo', photo_file, filename='photo.jpg', content_type='image/jpeg')
                logger.info(f"Отправка фото в чат {payload.chat_id}")
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
            json_data["reply_markup"] = payload.keyboard.model_dump(mode="json")

        logger.info(f"Редактирование сообщения: {json_data}")
        return await self._make_request(self.session.post(url, json=json_data))

    async def delete_message(self, chat_id: int, message_id: int) -> bool:
        url = f"{self.api_url}/deleteMessage"
        params = {"chat_id": chat_id, "message_id": message_id}
        logger.info(f"Удаление сообщения: {params}")
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
                if response.status == 429:
                    raise RateLimitError
                
                response.raise_for_status()

                data = await response.json()
                if data.get("ok") and data.get("result"):
                    logger.info(f"Сообщение успешно отправлено, message_id: {data['result']['message_id']}")
                    return data["result"]["message_id"]
                else:
                    logger.error(f"Ошибка от API Telegram (статус 200 OK): {data.get('description')}")
                    return None
        except RateLimitError:
            raise
        except aiohttp.ClientError as e:
            logger.error(f"Сетевая ошибка или ошибка статуса HTTP: {e}", exc_info=True)
            return None
        except Exception as e:
            logger.error(f"Неожиданная ошибка при выполнении запроса: {e}", exc_info=True)
            return None
