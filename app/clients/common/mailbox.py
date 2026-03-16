from enum import StrEnum, auto
from typing import Any

from pydantic import BaseModel, Field, model_validator

from app.utils.platform import build_actor_key


class MessageType(StrEnum):
    TEXT = auto()
    CALLBACK_QUERY = auto()
    NEW_CHAT_MEMBERS = auto()
    UNKNOWN = auto()


class PayloadAction(StrEnum):
    SEND = "send"
    EDIT = "edit"
    EDIT_CAPTION = "edit_caption"
    EDIT_MEDIA = "edit_media"
    DELETE = "delete"
    ANSWER_CALLBACK = "answer_callback"


class InlineKeyboardButton(BaseModel):
    text: str
    callback_data: str | None = None
    url: str | None = None


class InlineKeyboardMarkup(BaseModel):
    inline_keyboard: list[list[InlineKeyboardButton]]


class MessagePayload(BaseModel):
    chat_id: int
    action: PayloadAction = PayloadAction.SEND
    text: str | None = None
    photo_path: str | None = None
    photo_content_b64: str | None = None
    keyboard: InlineKeyboardMarkup | None = None
    message_id: int | None = None
    retry_count: int = 0
    trace_started_at: float | None = None
    callback_query_id: str | None = None
    show_alert: bool = False
    runtime_update: dict[str, Any] | None = None
    fsm_update: dict[str, Any] | None = None
    source_update_id: int | None = None
    source_user_id: int | None = None
    source_chat_id: int | None = None
    source_update_type: str | None = None
    source_platform: str | None = None
    target_platform: str | None = None
    actor_key: str | None = None

    class Config:
        from_attributes = True


class User(BaseModel):
    id: int
    is_bot: bool
    first_name: str
    last_name: str | None = None
    username: str | None = None


class Chat(BaseModel):
    id: int
    type: str
    title: str | None = None


class Message(BaseModel):
    message_id: int
    from_user: User | None = Field(None, alias="from")
    chat: Chat
    text: str | None = None
    new_chat_members: list[User] = []


class CallbackQuery(BaseModel):
    id: str
    from_user: User = Field(..., alias="from")
    message: Message | None = None
    data: str | None = None


class Update(BaseModel):
    update_id: int
    message: Message | None = None
    callback_query: CallbackQuery | None = None
    trace_started_at: float | None = None

    # Новые унифицированные поля
    from_user: User | None = None
    chat_id: int | None = None
    text: str | None = None
    source_platform: str | None = None
    actor_key: str | None = None
    user_id: int | None = None

    @model_validator(mode="after")
    def unify_fields(self) -> Update:
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
