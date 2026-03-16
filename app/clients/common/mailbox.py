from enum import Enum, auto
from typing import Optional, List, Any
from pydantic import BaseModel, Field, model_validator

from app.utils.platform import build_actor_key


class MessageType(str, Enum):
    TEXT = auto()
    CALLBACK_QUERY = auto()
    NEW_CHAT_MEMBERS = auto()
    UNKNOWN = auto()


class PayloadAction(str, Enum):
    SEND = "send"
    EDIT = "edit"
    EDIT_CAPTION = "edit_caption"
    EDIT_MEDIA = "edit_media"
    DELETE = "delete"
    ANSWER_CALLBACK = "answer_callback"


class InlineKeyboardButton(BaseModel):
    text: str
    callback_data: Optional[str] = None
    url: Optional[str] = None


class InlineKeyboardMarkup(BaseModel):
    inline_keyboard: List[List[InlineKeyboardButton]]


class MessagePayload(BaseModel):
    chat_id: int
    action: PayloadAction = PayloadAction.SEND
    text: Optional[str] = None
    photo_path: Optional[str] = None
    photo_content_b64: Optional[str] = None
    keyboard: Optional[InlineKeyboardMarkup] = None
    message_id: Optional[int] = None
    retry_count: int = 0
    trace_started_at: Optional[float] = None
    callback_query_id: Optional[str] = None
    show_alert: bool = False
    runtime_update: Optional[dict[str, Any]] = None
    fsm_update: Optional[dict[str, Any]] = None
    source_update_id: Optional[int] = None
    source_user_id: Optional[int] = None
    source_chat_id: Optional[int] = None
    source_update_type: Optional[str] = None
    source_platform: Optional[str] = None
    target_platform: Optional[str] = None
    actor_key: Optional[str] = None

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
    trace_started_at: Optional[float] = None

    # Новые унифицированные поля
    from_user: Optional[User] = None
    chat_id: Optional[int] = None
    text: Optional[str] = None
    source_platform: Optional[str] = None
    actor_key: Optional[str] = None
    user_id: Optional[int] = None

    @model_validator(mode='after')
    def unify_fields(self) -> 'Update':
        if self.message:
            self.from_user = self.message.from_user
            self.chat_id = self.message.chat.id
            self.text = self.message.text
        elif self.callback_query:
            self.from_user = self.callback_query.from_user
            if self.callback_query.message:
                self.chat_id = self.callback_query.message.chat.id
        if self.actor_key is None and self.from_user is not None:
            self.actor_key = build_actor_key(self.source_platform, self.from_user.id)
        return self

    @property
    def type(self) -> MessageType:
        if self.message and self.message.new_chat_members:
            return MessageType.NEW_CHAT_MEMBERS
        if self.message and self.message.text:
            return MessageType.TEXT
        if self.callback_query:
            return MessageType.CALLBACK_QUERY
        return MessageType.UNKNOWN
