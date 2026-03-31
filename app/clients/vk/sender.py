import asyncio
import base64
import contextlib
import json
import logging
import random
from time import monotonic

import aiohttp
from aio_pika.abc import AbstractIncomingMessage

from app.clients.vk.mailbox import InlineKeyboardButton, MessagePayload, PayloadAction
from app.store.queue.accessor import RabbitMQAccessor
from app.utils.log_context import get_update_context
from app.utils.runtime import load_runtime_state, save_runtime_state

logger = logging.getLogger(__name__)


class RateLimitError(Exception):
    pass


class Sender:
    RETRY_DELAY_SECONDS = 5
    MAX_KEYBOARD_BUTTONS = 10
    MAX_BUTTONS_PER_ROW = 5

    def __init__(self, app):
        self.app = app
        self.session: aiohttp.ClientSession = app.session
        self.rabbitmq: RabbitMQAccessor = app.rabbitmq
        self.api_url = app.config.VK_API_URL.rstrip("/")
        self.token = app.config.VK_TOKEN
        self.api_version = app.config.VK_API_VERSION
        self._task: asyncio.Task | None = None
        self.queue_name = "vk_sender_queue"

    async def _requeue_message(self, payload: MessagePayload):
        payload.retry_count += 1
        delay = self.RETRY_DELAY_SECONDS
        logger.warning(
            "VK rate limited. Retry in %s sec. Attempt=%s chat_id=%s",
            delay,
            payload.retry_count,
            payload.chat_id,
        )
        await asyncio.sleep(delay)
        await self.rabbitmq.publish(self.queue_name, payload.model_dump(mode="json"))

    async def _process_message(self, message: AbstractIncomingMessage):
        async with message.process():
            payload = MessagePayload.model_validate(
                json.loads(message.body.decode("utf-8"))
            )
            logger.info("VK sender dequeue %s", self._payload_brief(payload))
            try:
                send_started_at = monotonic()
                result = await self._dispatch_payload(payload)
                await self._apply_post_send_updates(payload, result)
                if payload.trace_started_at is not None:
                    logger.info(
                        "VK outgoing message completed chat_id=%s total=%.3fs sender=%.3fs",
                        payload.chat_id,
                        monotonic() - payload.trace_started_at,
                        monotonic() - send_started_at,
                    )
            except RateLimitError:
                await self._requeue_message(payload)
            except Exception as error:
                logger.error(
                    "VK sender unhandled error for %s: %s",
                    self._payload_brief(payload),
                    error,
                    exc_info=True,
                )

    async def _consume(self):
        sender_queue = await self.rabbitmq.get_queue(self.queue_name)
        await sender_queue.consume(self._process_message)
        logger.info("VK sender started listening queue '%s'.", self.queue_name)
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            logger.info("VK sender queue listening stopped.")

    async def start(self):
        if self._task:
            return
        self._task = asyncio.create_task(self._consume())
        logger.info("VK sender started.")

    async def stop(self):
        if not self._task:
            return
        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._task
        self._task = None
        logger.info("VK sender stopped.")

    async def _dispatch_payload(self, payload: MessagePayload) -> int | None:
        if payload.action == PayloadAction.DELETE:
            await self._delete_message(payload)
            return None
        if payload.action == PayloadAction.ANSWER_CALLBACK:
            await self._answer_callback_query(
                payload.callback_query_id, payload.text or "", payload.show_alert
            )
            return None
        if (
            payload.action == PayloadAction.EDIT
            or payload.action == PayloadAction.EDIT_CAPTION
            or payload.action == PayloadAction.EDIT_MEDIA
        ):
            return await self._edit_message(payload)
        return await self._send_message(payload)

    async def send_message(self, payload: MessagePayload) -> None:
        self._attach_context_metadata(payload)
        payload.action = PayloadAction.SEND
        await self.rabbitmq.publish(
            self.queue_name, payload.model_dump(mode="json", exclude_none=True)
        )

    async def edit_message(self, payload: MessagePayload) -> None:
        self._attach_context_metadata(payload)
        payload.action = PayloadAction.EDIT
        await self.rabbitmq.publish(
            self.queue_name, payload.model_dump(mode="json", exclude_none=True)
        )

    async def delete_message(self, chat_id: int, message_id: int) -> None:
        payload = MessagePayload(
            chat_id=chat_id,
            action=PayloadAction.DELETE,
            message_id=message_id,
        )
        self._attach_context_metadata(payload)
        await self.rabbitmq.publish(
            self.queue_name, payload.model_dump(mode="json", exclude_none=True)
        )

    async def answer_callback_query(
        self, callback_query_id: str, text: str, show_alert: bool = False
    ) -> None:
        payload = MessagePayload(
            chat_id=0,
            action=PayloadAction.ANSWER_CALLBACK,
            callback_query_id=callback_query_id,
            text=text,
            show_alert=show_alert,
        )
        self._attach_context_metadata(payload)
        await self.rabbitmq.publish(
            self.queue_name, payload.model_dump(mode="json", exclude_none=True)
        )

    async def _send_message(self, payload: MessagePayload) -> int | None:
        if payload.photo_content_b64 or payload.photo_path:
            return await self._send_photo(payload)
        return await self._send_text(payload)

    async def _send_text(self, payload: MessagePayload) -> int | None:
        params = {
            "peer_id": payload.chat_id,
            "message": payload.text or "",
            "random_id": random.randint(1, 2_147_483_647),
        }
        if payload.keyboard:
            params["keyboard"] = json.dumps(
                self._vk_keyboard(payload.keyboard.inline_keyboard), ensure_ascii=False
            )

        logger.info(
            "VK messages.send peer_id=%s text_len=%s keyboard_rows=%s",
            payload.chat_id,
            len(payload.text or ""),
            len(payload.keyboard.inline_keyboard) if payload.keyboard else 0,
        )
        result = await self._api_call("messages.send", params)
        if isinstance(result, int):
            return result
        return None

    async def _send_photo(self, payload: MessagePayload) -> int | None:
        attachment = await self._upload_photo_attachment(
            payload.chat_id, payload.photo_content_b64, payload.photo_path
        )
        if not attachment:
            return None

        params = {
            "peer_id": payload.chat_id,
            "message": payload.text or "",
            "attachment": attachment,
            "random_id": random.randint(1, 2_147_483_647),
        }
        if payload.keyboard:
            params["keyboard"] = json.dumps(
                self._vk_keyboard(payload.keyboard.inline_keyboard), ensure_ascii=False
            )

        logger.info(
            "VK messages.send(photo) peer_id=%s attachment=%s",
            payload.chat_id,
            attachment,
        )
        result = await self._api_call("messages.send", params)
        if isinstance(result, int):
            return result
        return None

    async def _edit_message(self, payload: MessagePayload) -> int | None:
        if payload.message_id is None:
            logger.warning(
                "VK edit skipped: message_id missing for chat_id=%s", payload.chat_id
            )
            return None

        params = {
            "peer_id": payload.chat_id,
            "message": payload.text or "",
        }
        prefer_conversation_id = self._is_callback_source(payload)
        if prefer_conversation_id:
            params["conversation_message_id"] = payload.message_id
        else:
            params["message_id"] = payload.message_id
        if payload.keyboard:
            params["keyboard"] = json.dumps(
                self._vk_keyboard(payload.keyboard.inline_keyboard), ensure_ascii=False
            )
        if payload.photo_content_b64 or payload.photo_path:
            attachment = await self._upload_photo_attachment(
                payload.chat_id, payload.photo_content_b64, payload.photo_path
            )
            if attachment:
                params["attachment"] = attachment

        logger.info(
            "VK messages.edit peer_id=%s message_id=%s id_mode=%s",
            payload.chat_id,
            payload.message_id,
            "conversation_message_id" if prefer_conversation_id else "message_id",
        )
        result = await self._api_call("messages.edit", params)
        if result is None:
            fallback_params = dict(params)
            if "message_id" in fallback_params:
                fallback_params.pop("message_id", None)
                fallback_params["conversation_message_id"] = payload.message_id
                fallback_mode = "conversation_message_id"
            else:
                fallback_params.pop("conversation_message_id", None)
                fallback_params["message_id"] = payload.message_id
                fallback_mode = "message_id"
            logger.info(
                "VK messages.edit fallback peer_id=%s message_id=%s id_mode=%s",
                payload.chat_id,
                payload.message_id,
                fallback_mode,
            )
            await self._api_call("messages.edit", fallback_params)
        return payload.message_id

    async def _delete_message(self, payload: MessagePayload) -> None:
        if payload.message_id is None:
            return
        prefer_conversation_id = self._is_callback_source(payload)
        if prefer_conversation_id:
            params = {
                "peer_id": payload.chat_id,
                "cmids": payload.message_id,
                "delete_for_all": 1,
            }
            mode = "cmids"
        else:
            params = {
                "message_ids": payload.message_id,
                "delete_for_all": 1,
            }
            mode = "message_ids"
        logger.info(
            "VK messages.delete chat_id=%s message_id=%s id_mode=%s",
            payload.chat_id,
            payload.message_id,
            mode,
        )
        result = await self._api_call("messages.delete", params)
        if result is None:
            if mode == "message_ids":
                fallback_params = {
                    "peer_id": payload.chat_id,
                    "cmids": payload.message_id,
                    "delete_for_all": 1,
                }
                fallback_mode = "cmids"
            else:
                fallback_params = {
                    "message_ids": payload.message_id,
                    "delete_for_all": 1,
                }
                fallback_mode = "message_ids"
            logger.info(
                "VK messages.delete fallback chat_id=%s message_id=%s id_mode=%s",
                payload.chat_id,
                payload.message_id,
                fallback_mode,
            )
            await self._api_call("messages.delete", fallback_params)

    async def _answer_callback_query(
        self, callback_query_id: str, text: str, show_alert: bool = False
    ):
        if not callback_query_id:
            return
        try:
            event_id, user_id_raw, peer_id_raw = callback_query_id.split(":", 2)
            user_id = int(user_id_raw)
            peer_id = int(peer_id_raw)
        except ValueError:
            logger.warning(
                "VK callback answer skipped: invalid callback id %s", callback_query_id
            )
            return

        event_data = {
            "type": "show_snackbar",
            "text": text[:90],
        }
        if show_alert:
            event_data["text"] = f"{text[:80]}"

        params = {
            "event_id": event_id,
            "user_id": user_id,
            "peer_id": peer_id,
            "event_data": json.dumps(event_data, ensure_ascii=False),
        }
        logger.info(
            "VK sendMessageEventAnswer event_id=%s user_id=%s peer_id=%s",
            event_id,
            user_id,
            peer_id,
        )
        await self._api_call("messages.sendMessageEventAnswer", params)

    async def _api_call(
        self, method: str, params: dict
    ) -> dict | list | int | bool | None:
        payload = {
            **params,
            "access_token": self.token,
            "v": self.api_version,
        }
        try:
            async with self.session.post(
                f"{self.api_url}/{method}", data=payload, timeout=20
            ) as response:
                response.raise_for_status()
                data = await response.json(content_type=None)
        except aiohttp.ClientError as error:
            logger.error(
                "VK transport error method=%s err=%s", method, error, exc_info=True
            )
            return None
        except TimeoutError:
            logger.warning("VK timeout method=%s", method)
            return None

        if data.get("error"):
            error_info = data["error"]
            if int(error_info.get("error_code", 0)) == 6:
                raise RateLimitError
            logger.error("VK API error method=%s payload=%s", method, error_info)
            return None

        return data.get("response")

    async def _upload_photo_attachment(
        self, peer_id: int, photo_b64: str | None, photo_path: str | None
    ) -> str | None:
        upload_server = await self._api_call(
            "photos.getMessagesUploadServer", {"peer_id": peer_id}
        )
        if not isinstance(upload_server, dict) or "upload_url" not in upload_server:
            logger.error(
                "VK upload server error for peer_id=%s response=%s",
                peer_id,
                upload_server,
            )
            return None

        try:
            if photo_b64:
                photo_bytes = base64.b64decode(photo_b64)
            else:
                with open(photo_path, "rb") as file:
                    photo_bytes = file.read()
        except FileNotFoundError:
            logger.error("VK photo file not found: %s", photo_path)
            return None

        form = aiohttp.FormData()
        form.add_field(
            "photo", photo_bytes, filename="image.png", content_type="image/png"
        )
        try:
            async with self.session.post(
                upload_server["upload_url"], data=form, timeout=30
            ) as response:
                response.raise_for_status()
                upload_result = await response.json(content_type=None)
        except aiohttp.ClientError as error:
            logger.error("VK upload transport error err=%s", error, exc_info=True)
            return None
        except TimeoutError:
            logger.warning("VK upload timeout")
            return None

        save_result = await self._api_call(
            "photos.saveMessagesPhoto",
            {
                "server": upload_result.get("server"),
                "photo": upload_result.get("photo"),
                "hash": upload_result.get("hash"),
            },
        )
        if not isinstance(save_result, list) or not save_result:
            logger.error("VK saveMessagesPhoto invalid response=%s", save_result)
            return None

        photo = save_result[0]
        owner_id = photo.get("owner_id")
        photo_id = photo.get("id")
        if owner_id is None or photo_id is None:
            logger.error("VK saveMessagesPhoto missing ids response=%s", photo)
            return None
        return f"photo{owner_id}_{photo_id}"

    @staticmethod
    def _vk_keyboard(rows: list[list[InlineKeyboardButton]]) -> dict:
        vk_rows = []
        total_buttons = 0
        for row in rows:
            vk_row = []
            for button in row:
                if total_buttons >= Sender.MAX_KEYBOARD_BUTTONS:
                    break
                if len(vk_row) >= Sender.MAX_BUTTONS_PER_ROW:
                    break
                if button.url:
                    vk_row.append(
                        {
                            "action": {
                                "type": "open_link",
                                "label": button.text,
                                "link": button.url,
                            },
                        }
                    )
                    total_buttons += 1
                    continue
                payload = json.dumps(
                    {"cmd": button.callback_data or "noop"}, ensure_ascii=False
                )
                vk_row.append(
                    {
                        "action": {
                            "type": "callback",
                            "label": button.text,
                            "payload": payload,
                        },
                        "color": "primary",
                    }
                )
                total_buttons += 1
            if vk_row:
                vk_rows.append(vk_row)
            if total_buttons >= Sender.MAX_KEYBOARD_BUTTONS:
                break
        source_buttons = sum(len(row) for row in rows)
        if source_buttons > total_buttons:
            logger.warning(
                "VK keyboard trimmed source_buttons=%s sent_buttons=%s max_buttons=%s",
                source_buttons,
                total_buttons,
                Sender.MAX_KEYBOARD_BUTTONS,
            )
        return {
            "inline": True,
            "buttons": vk_rows,
        }

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

    @staticmethod
    def _is_callback_source(payload: MessagePayload) -> bool:
        source = payload.source_update_type
        if source is None:
            return False
        normalized = str(source).strip().lower()
        return normalized in {"2", "callback_query", "messagetype.callback_query"}

    async def _apply_post_send_updates(
        self, payload: MessagePayload, message_id: int | None
    ) -> None:
        if payload.runtime_update:
            await self._apply_runtime_update(payload.runtime_update, message_id)
        if payload.fsm_update:
            await self._apply_fsm_update(payload.fsm_update, message_id)

    async def _apply_runtime_update(
        self, runtime_update: dict, message_id: int | None
    ) -> None:
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

    async def _apply_fsm_update(self, fsm_update: dict, message_id: int | None) -> None:
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
