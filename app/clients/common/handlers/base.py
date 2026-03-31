from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from app.clients.common.mailbox import MessagePayload, Update

if TYPE_CHECKING:
    from app.web.application import App


class BaseHandler(ABC):
    def __init__(self, app: App):
        self.app = app

    def cut_prefix(self, text: str | None) -> str:
        if not text:
            return ""
        if text.startswith(self.app.config.PREFIX):
            return text[1:]
        return text

    def command_name(self, text: str | None) -> str:
        raw = self.cut_prefix(text).strip()
        if not raw:
            return ""
        first_token = raw.split()[0]
        if "@" in first_token:
            first_token = first_token.split("@", 1)[0]
        return first_token

    @abstractmethod
    async def check(self, update: Update) -> bool:
        raise NotImplementedError

    @abstractmethod
    async def handle(self, update: Update) -> MessagePayload | None:
        raise NotImplementedError
