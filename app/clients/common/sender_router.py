from app.clients.common.mailbox import MessagePayload
from app.utils.log_context import get_update_context
from app.utils.platform import normalize_platform


class SenderRouter:
    def __init__(self, tg_sender=None, vk_sender=None):
        self.tg_sender = tg_sender
        self.vk_sender = vk_sender

    def _sender_for_platform(self, platform: str):
        normalized = normalize_platform(platform)
        if normalized == "VK":
            if self.vk_sender:
                return self.vk_sender
            if self.tg_sender:
                return self.tg_sender
            raise RuntimeError("No active senders configured")
        if self.tg_sender:
            return self.tg_sender
        if self.vk_sender:
            return self.vk_sender
        raise RuntimeError("No active senders configured")

    def _resolve_platform(self, payload: MessagePayload | None = None, explicit: str | None = None) -> str:
        if explicit:
            return normalize_platform(explicit)
        if payload and payload.target_platform:
            return normalize_platform(payload.target_platform)
        if payload and payload.source_platform:
            return normalize_platform(payload.source_platform)
        context = get_update_context() or {}
        return normalize_platform(context.get("platform"))

    async def send_message(self, payload: MessagePayload) -> None:
        platform = self._resolve_platform(payload)
        payload.target_platform = platform
        await self._sender_for_platform(platform).send_message(payload)

    async def edit_message(self, payload: MessagePayload) -> None:
        platform = self._resolve_platform(payload)
        payload.target_platform = platform
        await self._sender_for_platform(platform).edit_message(payload)

    async def delete_message(self, chat_id: int, message_id: int, *, target_platform: str | None = None) -> None:
        platform = self._resolve_platform(explicit=target_platform)
        await self._sender_for_platform(platform).delete_message(chat_id, message_id)

    async def answer_callback_query(
        self,
        callback_query_id: str,
        text: str,
        show_alert: bool = False,
        *,
        target_platform: str | None = None,
    ) -> None:
        platform = self._resolve_platform(explicit=target_platform)
        await self._sender_for_platform(platform).answer_callback_query(
            callback_query_id=callback_query_id,
            text=text,
            show_alert=show_alert,
        )
