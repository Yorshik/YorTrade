from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from app.clients.common.mailbox import MessagePayload, Update

if TYPE_CHECKING:
    from app.web.application import App


class StopProcessing:
    pass


STOP_PROCESSING = StopProcessing()


class BaseMiddleware(ABC):
    @abstractmethod
    async def process(
        self, update: Update, app: App
    ) -> MessagePayload | StopProcessing | None:
        """
        Метод для обработки обновления.
        Может вернуть MessagePayload, чтобы прервать цепочку и ответить пользователю.
        """
        raise NotImplementedError
