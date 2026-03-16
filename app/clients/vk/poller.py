import asyncio
import contextlib
import json
import logging
from time import monotonic

import aiohttp
from pydantic import ValidationError

from app.clients.vk.mailbox import Update
from app.store.queue.accessor import RabbitMQAccessor

logger = logging.getLogger(__name__)


class Poller:
    def __init__(self, app):
        self.app = app
        self.rabbitmq: RabbitMQAccessor = self.app.rabbitmq
        self.session: aiohttp.ClientSession = self.app.session
        self.api_url = self.app.config.VK_API_URL.rstrip("/")
        self.token = self.app.config.VK_TOKEN
        self.group_id = int(self.app.config.VK_GROUP_ID)
        self.api_version = self.app.config.VK_API_VERSION
        self._running = False
        self._task: asyncio.Task | None = None
        self._update_seq = 0
        self._user_cache: dict[int, dict[str, str]] = {}
        self._chat_title_cache: dict[int, str] = {}

    def _next_update_id(self) -> int:
        self._update_seq += 1
        return self._update_seq

    async def _api_call(self, method: str, params: dict | None = None) -> dict | None:
        params = params or {}
        params.update(
            {
                "access_token": self.token,
                "v": self.api_version,
            }
        )
        try:
            async with self.session.get(
                f"{self.api_url}/{method}", params=params, timeout=15
            ) as response:
                response.raise_for_status()
                payload = await response.json()
        except aiohttp.ClientError as error:
            logger.error(
                "VK api transport error method=%s err=%s", method, error, exc_info=True
            )
            return None
        except TimeoutError:
            logger.warning("VK api timeout method=%s", method)
            return None

        if payload.get("error"):
            logger.error("VK api error method=%s payload=%s", method, payload["error"])
            return None
        return payload.get("response")

    async def _get_longpoll_server(self) -> dict | None:
        return await self._api_call(
            "groups.getLongPollServer",
            {
                "group_id": self.group_id,
            },
        )

    async def _check_updates(
        self, server: str, key: str, ts: str, wait: int = 25
    ) -> dict | None:
        params = {
            "act": "a_check",
            "key": key,
            "ts": ts,
            "wait": wait,
            "mode": 2,
            "version": 3,
        }
        try:
            async with self.session.get(
                server, params=params, timeout=wait + 10
            ) as response:
                response.raise_for_status()
                return await response.json()
        except aiohttp.ClientError as error:
            logger.error("VK longpoll transport error err=%s", error, exc_info=True)
            return None
        except TimeoutError:
            logger.warning("VK longpoll timeout")
            return None

    @staticmethod
    def _chat_type(peer_id: int, from_id: int | None) -> str:
        if peer_id >= 2_000_000_000:
            return "group"
        if from_id and peer_id == from_id:
            return "private"
        return "group"

    async def _resolve_user_info(self, user_id: int) -> dict[str, str]:
        cached = self._user_cache.get(user_id)
        if cached is not None:
            return cached

        fallback_name = f"vk_user_{user_id}"
        user_info = {
            "first_name": fallback_name,
            "last_name": "",
            "username": fallback_name,
        }
        response = await self._api_call(
            "users.get",
            {
                "user_ids": user_id,
                "fields": "domain",
            },
        )
        if isinstance(response, list) and response:
            user_payload = response[0] or {}
            first_name = str(user_payload.get("first_name") or fallback_name).strip()
            last_name = str(user_payload.get("last_name") or "").strip()
            full_name = " ".join(
                part for part in [first_name, last_name] if part
            ).strip()
            username = (
                full_name or str(user_payload.get("domain") or fallback_name).strip()
            )
            user_info = {
                "first_name": first_name or fallback_name,
                "last_name": last_name,
                "username": username or fallback_name,
            }

        self._user_cache[user_id] = user_info
        return user_info

    async def _resolve_chat_title(self, peer_id: int) -> str | None:
        if peer_id < 2_000_000_000:
            return None
        cached = self._chat_title_cache.get(peer_id)
        if cached is not None:
            return cached

        title = f"vk_chat_{peer_id}"
        response = await self._api_call(
            "messages.getConversationsById",
            {
                "peer_ids": peer_id,
            },
        )
        if isinstance(response, dict):
            items = response.get("items") or []
            if items and isinstance(items[0], dict):
                conversation = items[0].get("conversation") or {}
                chat_settings = (
                    conversation.get("chat_settings")
                    or items[0].get("chat_settings")
                    or {}
                )
                chat_title = chat_settings.get("title")
                if chat_title:
                    title = str(chat_title)

        self._chat_title_cache[peer_id] = title
        return title

    async def _convert_message_new(self, event: dict) -> dict | None:
        obj = event.get("object") or {}
        message = obj.get("message") or {}
        peer_id = int(message.get("peer_id") or 0)
        from_id = int(message.get("from_id") or 0)
        if not peer_id or not from_id:
            return None

        user_info = await self._resolve_user_info(from_id)
        chat_title = await self._resolve_chat_title(peer_id)
        update_id = self._next_update_id()
        return {
            "update_id": update_id,
            "message": {
                "message_id": int(
                    message.get("id")
                    or message.get("conversation_message_id")
                    or update_id
                ),
                "from": {
                    "id": from_id,
                    "is_bot": False,
                    "first_name": user_info["first_name"],
                    "last_name": user_info["last_name"] or None,
                    "username": user_info["username"],
                },
                "chat": {
                    "id": peer_id,
                    "type": self._chat_type(peer_id, from_id),
                    "title": chat_title,
                },
                "text": message.get("text") or "",
                "new_chat_members": [],
            },
        }

    async def _convert_message_event(self, event: dict) -> dict | None:
        obj = event.get("object") or {}
        peer_id = int(obj.get("peer_id") or 0)
        user_id = int(obj.get("user_id") or 0)
        event_id = obj.get("event_id")
        if not peer_id or not user_id or not event_id:
            return None

        user_info = await self._resolve_user_info(user_id)
        chat_title = await self._resolve_chat_title(peer_id)
        payload = obj.get("payload")
        callback_data = self._extract_callback_data(payload)

        update_id = self._next_update_id()
        callback_id = f"{event_id}:{user_id}:{peer_id}"
        return {
            "update_id": update_id,
            "callback_query": {
                "id": callback_id,
                "from": {
                    "id": user_id,
                    "is_bot": False,
                    "first_name": user_info["first_name"],
                    "last_name": user_info["last_name"] or None,
                    "username": user_info["username"],
                },
                "message": {
                    "message_id": int(obj.get("conversation_message_id") or update_id),
                    "chat": {
                        "id": peer_id,
                        "type": self._chat_type(peer_id, user_id),
                        "title": chat_title,
                    },
                    "text": None,
                    "new_chat_members": [],
                },
                "data": callback_data,
            },
        }

    @staticmethod
    def _extract_callback_data(payload: object) -> str:
        if isinstance(payload, dict):
            cmd = payload.get("cmd")
            if cmd is not None:
                return str(cmd)
            return json.dumps(payload, ensure_ascii=False)

        if isinstance(payload, str):
            raw = payload.strip()
            if not raw:
                return ""
            if raw.startswith("{") and raw.endswith("}"):
                try:
                    parsed = json.loads(raw)
                except json.JSONDecodeError:
                    return raw
                if isinstance(parsed, dict) and parsed.get("cmd") is not None:
                    return str(parsed["cmd"])
            return raw

        return ""

    async def _convert_event(self, event: dict) -> dict | None:
        event_type = event.get("type")
        if event_type == "message_new":
            return await self._convert_message_new(event)
        if event_type == "message_event":
            return await self._convert_message_event(event)
        return None

    async def _poll(self):
        updates_queue_name = "vk_updates"
        logger.info("VK poller started.")
        while self._running:
            server_data = await self._get_longpoll_server()
            if not server_data:
                await asyncio.sleep(2)
                continue

            server = server_data["server"]
            key = server_data["key"]
            ts = str(server_data["ts"])

            while self._running:
                updates_response = await self._check_updates(server, key, ts)
                if not updates_response:
                    break
                if "failed" in updates_response:
                    logger.warning(
                        "VK longpoll reset required payload=%s", updates_response
                    )
                    break

                ts = str(updates_response.get("ts", ts))
                updates = updates_response.get("updates") or []
                if not updates:
                    continue

                logger.info("VK poller batch size=%s", len(updates))
                for event in updates:
                    normalized = await self._convert_event(event)
                    if not normalized:
                        continue
                    normalized["trace_started_at"] = monotonic()
                    normalized["source_platform"] = "VK"
                    try:
                        Update.model_validate(normalized)
                    except ValidationError as error:
                        logger.error(
                            "VK poller skipped invalid update payload err=%s payload=%s",
                            error,
                            normalized,
                        )
                        continue
                    logger.info(
                        "VK poller enqueue update_id=%s kind=%s chat_id=%s from_user=%s text=%s callback=%s",
                        normalized.get("update_id"),
                        "callback_query"
                        if normalized.get("callback_query")
                        else "message",
                        (
                            normalized.get("message")
                            or (normalized.get("callback_query") or {}).get("message")
                            or {}
                        )
                        .get("chat", {})
                        .get("id"),
                        (normalized.get("message") or {}).get("from", {}).get("id")
                        or (normalized.get("callback_query") or {})
                        .get("from", {})
                        .get("id"),
                        ((normalized.get("message") or {}).get("text") or "")[:120],
                        ((normalized.get("callback_query") or {}).get("data") or "")[
                            :120
                        ],
                    )
                    await self.rabbitmq.publish(updates_queue_name, normalized)

    async def start(self):
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._poll())
        logger.info("VK poller running.")

    async def stop(self):
        if not self._running:
            return
        self._running = False
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        logger.info("VK poller stopped.")
