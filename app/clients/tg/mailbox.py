from enum import Enum, auto
from typing import Optional, List
from pydantic import BaseModel, Field


class MessageType(str, Enum):
    TEXT = auto()
    CALLBACK_QUERY = auto()
    NEW_CHAT_MEMBERS = auto()
    UNKNOWN = auto()


class InlineKeyboardButton(BaseModel):
    text: str
    callback_data: Optional[str] = None
    url: Optional[str] = None


class InlineKeyboardMarkup(BaseModel):
    inline_keyboard: List[List[InlineKeyboardButton]]


class MessagePayload(BaseModel):
    chat_id: int
    text: Optional[str] = None
    photo_path: Optional[str] = None
    keyboard: Optional[InlineKeyboardMarkup] = None
    message_id: Optional[int] = None
    retry_count: int = 0

    class Config:
        from_attributes = True


class User(BaseModel):
    id: int
    is_bot: bool
    first_name: str
    last_name: Optional[str] = None
    username: Optional[str] = None


class Chat(BaseModel):
    id: int
    type: str
    title: Optional[str] = None


class Message(BaseModel):
    message_id: int
    from_user: Optional[User] = Field(None, alias="from")
    chat: Chat
    text: Optional[str] = None
    new_chat_members: List[User] = []


class CallbackQuery(BaseModel):
    id: str
    from_user: User = Field(..., alias="from")
    message: Optional[Message] = None
    data: Optional[str] = None


class Update(BaseModel):
    update_id: int
    message: Optional[Message] = None
    callback_query: Optional[CallbackQuery] = None

    @property
    def type(self) -> MessageType:
        if self.message and self.message.new_chat_members:
            return MessageType.NEW_CHAT_MEMBERS
        if self.message and self.message.text:
            return MessageType.TEXT
        if self.callback_query:
            return MessageType.CALLBACK_QUERY
        return MessageType.UNKNOWN

    @property
    def get_upd_from_user(self) -> Optional[User]:
        if self.message:
            return self.message.from_user
        if self.callback_query:
            return self.callback_query.from_user
        return None

    @property
    def get_chat_id(self) -> Optional[int]:
        if self.message:
            return self.message.chat.id
        if self.callback_query and self.callback_query.message:
            return self.callback_query.message.chat.id
        return None

    @property
    def get_text(self) -> Optional[str]:
        if self.message:
            return self.message.text
        if self.callback_query:
            return self.callback_query.data
        return None
