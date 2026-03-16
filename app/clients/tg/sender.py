import asyncio
import base64
import aiohttp
import json
import logging
from time import monotonic
from typing import Optional

from aio_pika.abc import AbstractIncomingMessage
from app.clients.tg.mailbox import MessagePayload, PayloadAction
from app.store.queue.accessor import RabbitMQAccessor
from app.utils.log_context import get_update_context
from app.utils.runtime import load_runtime_state, save_runtime_state

logger = logging.getLogger(__name__)


class RateLimitError(Exception):
    pass


class MessageNotModifiedError(Exception):
    pass


class Sender:
    RETRY_DELAY_SECONDS = 5
    TRANSPORT_RETRY_COUNT = 2
    TRANSPORT_RETRY_DELAY_SECONDS = 0.8
    MAX_PHOTO_CAPTION_LENGTH = 1024

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
            logger.info("Sender dequeue %s", self._payload_brief(payload))
            
            try:
                send_started_at = monotonic()
                result = await self._dispatch_payload(payload)
                await self._apply_post_send_updates(payload, result)
                if payload.trace_started_at is not None:
                    logger.info(
                        "Outgoing message for chat_id=%s completed in %.3f s total, sender stage %.3f s",
                        payload.chat_id,
                        monotonic() - payload.trace_started_at,
                        monotonic() - send_started_at,
                    )
            except RateLimitError:
                await self._requeue_message(payload)
            except Exception as e:
                logger.error("Sender unhandled error for %s: %s", self._payload_brief(payload), e, exc_info=True)

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

    async def _dispatch_payload(self, payload: MessagePayload) -> Optional[int]:
        if payload.action == PayloadAction.DELETE:
            await self._delete_message(payload.chat_id, payload.message_id)
            return None
        if payload.action == PayloadAction.ANSWER_CALLBACK:
            await self._answer_callback_query(payload.callback_query_id, payload.text or "", payload.show_alert)
            return None
        if payload.action == PayloadAction.EDIT_MEDIA:
            return await self._edit_message_media(payload)
        if payload.action == PayloadAction.EDIT_CAPTION:
            return await self._edit_message_caption(payload)
        if payload.action == PayloadAction.EDIT:
            return await self._edit_message(payload)
        return await self._send_message(payload)

    async def _send_message(self, payload: MessagePayload) -> Optional[int]:
        if payload.photo_content_b64 or payload.photo_path:
            return await self._send_photo(payload)
        elif payload.text:
            return await self._send_text(payload)
        else:
            logger.warning("Для отправки сообщения нужен хотя бы текст или фото.")
            return None

    async def send_message(self, payload: MessagePayload) -> None:
        self._attach_context_metadata(payload)
        payload.action = PayloadAction.SEND
        await self.rabbitmq.publish(self.queue_name, payload.model_dump(mode="json", exclude_none=True))

    async def edit_message(self, payload: MessagePayload) -> None:
        self._attach_context_metadata(payload)
        payload.action = PayloadAction.EDIT
        await self.rabbitmq.publish(self.queue_name, payload.model_dump(mode="json", exclude_none=True))

    async def delete_message(self, chat_id: int, message_id: int) -> None:
        payload = MessagePayload(
            chat_id=chat_id,
            action=PayloadAction.DELETE,
            message_id=message_id,
        )
        self._attach_context_metadata(payload)
        await self.rabbitmq.publish(
            self.queue_name,
            payload.model_dump(mode="json", exclude_none=True),
        )

    async def answer_callback_query(self, callback_query_id: str, text: str, show_alert: bool = False) -> None:
        payload = MessagePayload(
            chat_id=0,
            action=PayloadAction.ANSWER_CALLBACK,
            callback_query_id=callback_query_id,
            text=text,
            show_alert=show_alert,
        )
        self._attach_context_metadata(payload)
        await self.rabbitmq.publish(
            self.queue_name,
            payload.model_dump(mode="json", exclude_none=True),
        )

    async def _send_text(self, payload: MessagePayload) -> Optional[int]:
        url = f"{self.api_url}/sendMessage"
        json_data = {"chat_id": payload.chat_id, "text": payload.text}
        if payload.keyboard:
            json_data["reply_markup"] = payload.keyboard.model_dump(mode="json", exclude_none=True)
        
        logger.info(
            "TG sendMessage chat_id=%s text_len=%s keyboard_rows=%s",
            payload.chat_id,
            len(payload.text or ""),
            len(payload.keyboard.inline_keyboard) if payload.keyboard else 0,
        )
        return await self._make_request(
            self.session.post(url, json=json_data),
            operation="sendMessage",
            context=self._payload_brief(payload),
        )

    async def _send_photo(self, payload: MessagePayload) -> Optional[int]:
        url = f"{self.api_url}/sendPhoto"
        caption = (payload.text or "")[: self.MAX_PHOTO_CAPTION_LENGTH]

        try:
            if payload.photo_content_b64:
                photo_bytes = base64.b64decode(payload.photo_content_b64)
                filename = "chart.png"
                content_type = "image/png"
            else:
                with open(payload.photo_path, 'rb') as photo_file:
                    photo_bytes = photo_file.read()
                filename = "photo.jpg"
                content_type = "image/jpeg"
        except FileNotFoundError:
            logger.error(f"Файл не найден {payload.photo_path}")
            return None
        except Exception as e:
            logger.error(f"Ошибка при подготовке фото: {e}", exc_info=True)
            return None

        for attempt in range(1, self.TRANSPORT_RETRY_COUNT + 1):
            data = aiohttp.FormData()
            data.add_field('chat_id', str(payload.chat_id))
            if caption:
                data.add_field('caption', caption)
            if payload.keyboard:
                data.add_field('reply_markup', payload.keyboard.model_dump_json(exclude_none=True))
            data.add_field('photo', photo_bytes, filename=filename, content_type=content_type)

            logger.info(
                "TG sendPhoto chat_id=%s caption_len=%s source=%s attempt=%s/%s",
                payload.chat_id,
                len(caption),
                "b64" if payload.photo_content_b64 else "path",
                attempt,
                self.TRANSPORT_RETRY_COUNT,
            )
            result = await self._make_request(
                self.session.post(url, data=data),
                operation="sendPhoto",
                context=self._payload_brief(payload),
            )
            if result is not None:
                return result
            if attempt < self.TRANSPORT_RETRY_COUNT:
                await asyncio.sleep(self.TRANSPORT_RETRY_DELAY_SECONDS)

        if payload.runtime_update or payload.fsm_update:
            logger.warning(
                "TG sendPhoto failed without text fallback for runtime/fsm payload chat_id=%s context=%s",
                payload.chat_id,
                self._payload_brief(payload),
            )
            return None

        logger.warning(
            "TG sendPhoto fallback to sendMessage chat_id=%s context=%s",
            payload.chat_id,
            self._payload_brief(payload),
        )
        text_payload = payload.model_copy(update={"photo_content_b64": None, "photo_path": None})
        return await self._send_text(text_payload)

    async def _edit_message(self, payload: MessagePayload) -> Optional[int]:
        if payload.photo_content_b64 or payload.photo_path:
            media_result = await self._edit_message_media(payload)
            if media_result is not None:
                return media_result

            logger.warning(
                "TG media edit fallback to new SEND chat_id=%s message_id=%s context=%s",
                payload.chat_id,
                payload.message_id,
                self._payload_brief(payload),
            )
            return await self._resend_as_new_message(payload)

        text_result = await self._edit_message_text(payload)
        if text_result is not None:
            return text_result
        logger.warning(
            "TG edit text fallback to new SEND chat_id=%s message_id=%s context=%s",
            payload.chat_id,
            payload.message_id,
            self._payload_brief(payload),
        )
        return await self._resend_as_new_message(payload)

    async def _resend_as_new_message(self, payload: MessagePayload) -> Optional[int]:
        old_message_id = payload.message_id
        resend_payload = payload.model_copy(update={"message_id": None})
        new_message_id = await self._send_message(resend_payload)
        if new_message_id is None:
            return None
        if old_message_id is not None:
            await self._delete_message(payload.chat_id, old_message_id)
        return new_message_id

    async def _edit_message_text(self, payload: MessagePayload) -> Optional[int]:
        url = f"{self.api_url}/editMessageText"
        json_data = {
            "chat_id": payload.chat_id,
            "message_id": payload.message_id,
            "text": payload.text or ""
        }
        if payload.keyboard:
            json_data["reply_markup"] = payload.keyboard.model_dump(mode="json", exclude_none=True)

        logger.info(
            "TG editMessageText chat_id=%s message_id=%s text_len=%s keyboard_rows=%s",
            payload.chat_id,
            payload.message_id,
            len(payload.text or ""),
            len(payload.keyboard.inline_keyboard) if payload.keyboard else 0,
        )
        return await self._make_request(
            self.session.post(url, json=json_data),
            operation="editMessageText",
            context=self._payload_brief(payload),
            noop_message_id=payload.message_id,
        )

    async def _edit_message_caption(self, payload: MessagePayload) -> Optional[int]:
        url = f"{self.api_url}/editMessageCaption"
        caption = (payload.text or "")[: self.MAX_PHOTO_CAPTION_LENGTH]
        json_data = {
            "chat_id": payload.chat_id,
            "message_id": payload.message_id,
            "caption": caption,
        }
        if payload.keyboard:
            json_data["reply_markup"] = payload.keyboard.model_dump(mode="json", exclude_none=True)

        logger.info(
            "TG editMessageCaption chat_id=%s message_id=%s caption_len=%s keyboard_rows=%s",
            payload.chat_id,
            payload.message_id,
            len(caption),
            len(payload.keyboard.inline_keyboard) if payload.keyboard else 0,
        )
        return await self._make_request(
            self.session.post(url, json=json_data),
            operation="editMessageCaption",
            context=self._payload_brief(payload),
            noop_message_id=payload.message_id,
        )

    async def _edit_message_media(self, payload: MessagePayload) -> Optional[int]:
        url = f"{self.api_url}/editMessageMedia"

        try:
            if payload.photo_content_b64:
                photo_bytes = base64.b64decode(payload.photo_content_b64)
            else:
                with open(payload.photo_path, "rb") as photo_file:
                    photo_bytes = photo_file.read()
        except FileNotFoundError:
            logger.error("File not found for media edit: %s", payload.photo_path)
            return None
        except Exception as error:
            logger.error("Failed to prepare media edit payload: %s", error, exc_info=True)
            return None

        for attempt in range(1, self.TRANSPORT_RETRY_COUNT + 1):
            data = aiohttp.FormData()
            data.add_field("chat_id", str(payload.chat_id))
            data.add_field("message_id", str(payload.message_id))

            media = {
                "type": "photo",
                "media": "attach://photo",
            }
            caption = (payload.text or "")[: self.MAX_PHOTO_CAPTION_LENGTH]
            if payload.text:
                media["caption"] = caption
            data.add_field("media", json.dumps(media))
            if payload.keyboard:
                data.add_field("reply_markup", payload.keyboard.model_dump_json(exclude_none=True))
            data.add_field("photo", photo_bytes, filename="chart.png", content_type="image/png")

            logger.info(
                "TG editMessageMedia chat_id=%s message_id=%s caption_len=%s keyboard_rows=%s attempt=%s/%s",
                payload.chat_id,
                payload.message_id,
                len(caption),
                len(payload.keyboard.inline_keyboard) if payload.keyboard else 0,
                attempt,
                self.TRANSPORT_RETRY_COUNT,
            )
            result = await self._make_request(
                self.session.post(url, data=data),
                operation="editMessageMedia",
                context=self._payload_brief(payload),
                noop_message_id=payload.message_id,
            )
            if result is not None:
                return result
            if attempt < self.TRANSPORT_RETRY_COUNT:
                await asyncio.sleep(self.TRANSPORT_RETRY_DELAY_SECONDS)
        return None

    async def _delete_message(self, chat_id: int, message_id: int) -> bool:
        url = f"{self.api_url}/deleteMessage"
        params = {"chat_id": chat_id, "message_id": message_id}
        logger.info("TG deleteMessage chat_id=%s message_id=%s", chat_id, message_id)
        try:
            async with self.session.post(url, json=params) as response:
                response.raise_for_status()
                data = await response.json()
                return data.get("ok", False)
        except aiohttp.ClientError as e:
            logger.error(f"Ошибка при удалении сообщения: {e}", exc_info=True)
            return False

    async def _answer_callback_query(self, callback_query_id: str, text: str, show_alert: bool = False):
        url = f"{self.api_url}/answerCallbackQuery"
        json_data = {
            "callback_query_id": callback_query_id,
            "text": text,
            "show_alert": show_alert,
        }
        logger.info(
            "TG answerCallbackQuery callback_id=%s text_len=%s alert=%s",
            callback_query_id,
            len(text),
            show_alert,
        )
        try:
            async with self.session.post(url, json=json_data) as response:
                response.raise_for_status()
        except aiohttp.ClientError as e:
            logger.error(f"Ошибка при ответе на колбэк: {e}", exc_info=True)

    async def _make_request(
        self,
        request_context,
        operation: str,
        context: str,
        noop_message_id: int | None = None,
    ) -> Optional[int]:
        try:
            async with request_context as response:
                if response.status == 429:
                    raise RateLimitError
                data = await response.json()
                if response.status >= 400:
                    description = data.get("description", "")
                    if "message is not modified" in description.lower():
                        raise MessageNotModifiedError
                    logger.error(
                        "Telegram API error op=%s status=%s reason=%s context=%s",
                        operation,
                        response.status,
                        description,
                        context,
                    )
                    response.raise_for_status()

                if data.get("ok") and data.get("result"):
                    message_id = data["result"].get("message_id")
                    logger.info("Telegram API ok op=%s message_id=%s context=%s", operation, message_id, context)
                    return message_id

                logger.error(
                    "Telegram API unexpected payload op=%s reason=%s context=%s",
                    operation,
                    data.get("description"),
                    context,
                )
                return None
        except RateLimitError:
            raise
        except MessageNotModifiedError:
            logger.info("Telegram API no-op op=%s reason=message_not_modified context=%s", operation, context)
            return noop_message_id
        except aiohttp.ClientError as e:
            logger.error("Telegram transport error op=%s context=%s err=%s", operation, context, e, exc_info=True)
            return None
        except Exception as e:
            logger.error("Telegram unexpected error op=%s context=%s err=%s", operation, context, e, exc_info=True)
            return None

    @staticmethod
    def _payload_brief(payload: MessagePayload) -> str:
        return (
            f"action={payload.action.value} "
            f"chat_id={payload.chat_id} "
            f"message_id={payload.message_id} "
            f"text_len={len(payload.text or '')} "
            f"photo={bool(payload.photo_content_b64 or payload.photo_path)} "
            f"retry={payload.retry_count} "
            f"source_update={payload.source_update_id} "
            f"source_user={payload.source_user_id} "
            f"source_chat={payload.source_chat_id} "
            f"source_type={payload.source_update_type} "
            f"source_platform={payload.source_platform} "
            f"actor_key={payload.actor_key}"
        )

    @staticmethod
    def _attach_context_metadata(payload: MessagePayload) -> None:
        context = get_update_context()
        if not context:
            return
        if payload.source_update_id is None:
            payload.source_update_id = context.get("update_id")
        if payload.source_user_id is None:
            payload.source_user_id = context.get("user_id")
        if payload.source_chat_id is None:
            payload.source_chat_id = context.get("chat_id")
        if payload.source_update_type is None:
            payload.source_update_type = context.get("update_type")
        if payload.source_platform is None:
            payload.source_platform = context.get("platform")
        if payload.actor_key is None:
            payload.actor_key = context.get("actor_key")

    async def _apply_post_send_updates(self, payload: MessagePayload, message_id: Optional[int]) -> None:
        if payload.runtime_update:
            await self._apply_runtime_update(payload.runtime_update, message_id)
        if payload.fsm_update:
            await self._apply_fsm_update(payload.fsm_update, message_id)

    async def _apply_runtime_update(self, runtime_update: dict, message_id: Optional[int]) -> None:
        game_id = runtime_update["game_id"]
        state = await load_runtime_state(self.app, game_id)
        if state is None:
            return
        pending_field = runtime_update.get("pending_field")
        if pending_field:
            state[pending_field] = False
            pending_since_field = f"{pending_field}_since"
            if pending_since_field in state:
                state[pending_since_field] = None
        message_field = runtime_update.get("message_field")
        if message_field and message_id is not None:
            state[message_field] = message_id
        await save_runtime_state(self.app, state)

    async def _apply_fsm_update(self, fsm_update: dict, message_id: Optional[int]) -> None:
        data = dict(fsm_update.get("data", {}))
        pending_field = fsm_update.get("pending_field")
        if pending_field:
            data[pending_field] = False
            pending_since_field = f"{pending_field}_since"
            if pending_since_field in data:
                data[pending_since_field] = None
        message_field = fsm_update.get("message_field")
        if message_field and message_id is not None:
            data[message_field] = message_id
        await self.app.fsm.set_state(
            fsm_update["user_id"],
            fsm_update["state"],
            data,
            platform=fsm_update.get("platform"),
        )
