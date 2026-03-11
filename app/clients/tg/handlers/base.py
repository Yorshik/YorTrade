from abc import ABC, abstractmethod
from typing import Optional, TYPE_CHECKING

from app.clients.tg.mailbox import Update, MessagePayload

if TYPE_CHECKING:
    from app.web.application import App


class BaseHandler(ABC):
    def __init__(self, app: App):
        self.app = app

    @abstractmethod
    def check(self, update: Update) -> bool:
        raise NotImplementedError

    @abstractmethod
    async def handle(self, update: Update) -> Optional[MessagePayload]:
        raise NotImplementedError
