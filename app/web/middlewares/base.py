from abc import ABC, abstractmethod
from typing import Optional
from app.clients.common.mailbox import Update, MessagePayload
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.web.application import App


class StopProcessing:
    pass


STOP_PROCESSING = StopProcessing()


class BaseMiddleware(ABC):
    @abstractmethod
    async def process(self, update: Update, app: App) -> Optional[MessagePayload | StopProcessing]:
        """
        Метод для обработки обновления.
        Может вернуть MessagePayload, чтобы прервать цепочку и ответить пользователю.
        """
        raise NotImplementedError
