import asyncio
import json
import logging
from time import monotonic
from typing import Optional, Type

from aio_pika.abc import AbstractIncomingMessage

from app.clients.common.mailbox import Update as CommonUpdate
from app.store.queue.accessor import RabbitMQAccessor
from app.utils.log_context import reset_update_context, set_update_context
from app.utils.platform import build_actor_key, normalize_platform

logger = logging.getLogger(__name__)


class Worker:
    def __init__(
        self,
        app,
        *,
        updates_queue_name: str,
        sender_queue_name: str,
        update_model: Type[CommonUpdate],
        source_platform: str,
    ):
        self.app = app
        self.rabbitmq: RabbitMQAccessor = app.rabbitmq
        self.handler_factory = app.handler_factory
        self.middleware_factory = app.middleware_factory
        self._task: Optional[asyncio.Task] = None
        self.updates_queue_name = updates_queue_name
        self.sender_queue_name = sender_queue_name
        self.update_model = update_model
        self.source_platform = normalize_platform(source_platform)

    async def _process_message(self, message: AbstractIncomingMessage):
        async with message.process():
            context_token = None
            try:
                update_json = json.loads(message.body.decode("utf-8"))
                update = self.update_model.model_validate(update_json)
                if update.source_platform is None:
                    update.source_platform = self.source_platform
                if update.actor_key is None and update.from_user is not None:
                    update.actor_key = build_actor_key(update.source_platform, update.from_user.id)
                context_token = set_update_context(
                    update_id=update.update_id,
                    user_id=update.from_user.id if update.from_user else None,
                    chat_id=update.chat_id,
                    update_type=update.type.value if update.type else None,
                    platform=update.source_platform,
                    actor_key=update.actor_key,
                )
                logger.info(
                    "Worker received update_id=%s type=%s chat_id=%s from_user=%s text=%s callback=%s",
                    update.update_id,
                    update.type.value,
                    update.chat_id,
                    update.from_user.id if update.from_user else None,
                    (update.text or "")[:120],
                    (update.callback_query.data if update.callback_query else "")[:120],
                )
                if update.trace_started_at is not None:
                    logger.info(
                        "Update %s reached worker in %.3f s",
                        update.update_id,
                        monotonic() - update.trace_started_at,
                    )
                response_payload = await self.middleware_factory.process_update(update)
                if not response_payload:
                    response_payload = await self.handler_factory.handle_update(update)
                if response_payload:
                    self._attach_source_metadata(response_payload, update)
                    response_payload.trace_started_at = update.trace_started_at
                    logger.info(
                        "Worker queued sender action=%s chat_id=%s message_id=%s text_len=%s photo=%s source_update=%s source_user=%s",
                        response_payload.action.value,
                        response_payload.chat_id,
                        response_payload.message_id,
                        len(response_payload.text or ""),
                        bool(response_payload.photo_content_b64 or response_payload.photo_path),
                        response_payload.source_update_id,
                        response_payload.source_user_id,
                    )
                    await self.rabbitmq.publish(
                        self.sender_queue_name,
                        response_payload.model_dump(mode="json"),
                    )
                else:
                    logger.info(
                        "Worker no direct payload for update_id=%s (handled via side effects or no handler).",
                        update.update_id,
                    )
            except Exception as error:
                logger.error("Worker failed to process message: %s", error, exc_info=True)
            finally:
                if context_token is not None:
                    reset_update_context(context_token)

    @staticmethod
    def _attach_source_metadata(payload, update: CommonUpdate) -> None:
        if payload.source_update_id is None:
            payload.source_update_id = update.update_id
        if payload.source_user_id is None:
            payload.source_user_id = update.from_user.id if update.from_user else None
        if payload.source_chat_id is None:
            payload.source_chat_id = update.chat_id
        if payload.source_update_type is None:
            payload.source_update_type = update.type.value
        if payload.source_platform is None:
            payload.source_platform = update.source_platform
        if payload.actor_key is None:
            payload.actor_key = update.actor_key

    async def _consume(self):
        updates_queue = await self.rabbitmq.get_queue(self.updates_queue_name)
        await updates_queue.consume(self._process_message)
        logger.info("Worker started listening queue '%s'.", self.updates_queue_name)
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            logger.info("Worker queue listening stopped.")

    async def start(self):
        if not self._task:
            self._task = asyncio.create_task(self._consume())
            logger.info("Worker started.")

    async def stop(self):
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            logger.info("Worker stopped.")
