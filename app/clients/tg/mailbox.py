from dataclasses import dataclass
from enum import Enum
from typing import Optional, List


class MessageType(Enum):
    TEXT = "text"
    CALLBACK_QUERY = "callback_query"
    NEW_CHAT_MEMBERS = "new_chat_members"  # Новый тип
    UNKNOWN = "unknown"


@dataclass
class UpdateObject:
    raw_update: dict
    message_type: MessageType
    chat_id: int
    user_id: int
    command: Optional[str] = None
    data: Optional[str] = None
    # Новое поле для информации о новых участниках
    new_chat_members: Optional[List[dict]] = None

    @classmethod
    def from_dict(cls, data: dict) -> "UpdateObject":
        raw_update = data
        if "message" in data:
            message = data["message"]
            chat_id = message["chat"]["id"]
            user_id = message["from"]["id"]

            # Проверяем, был ли кто-то добавлен в чат
            if "new_chat_members" in message:
                return cls(
                    raw_update=raw_update,
                    message_type=MessageType.NEW_CHAT_MEMBERS,
                    chat_id=chat_id,
                    user_id=user_id,
                    new_chat_members=message["new_chat_members"]
                )

            if "text" in message:
                text = message["text"]
                parts = text.split()
                command = parts[0][1:] if text.startswith("/") else None
                data_text = " ".join(parts[1:]) if command else text
                return cls(
                    raw_update=raw_update,
                    message_type=MessageType.TEXT,
                    chat_id=chat_id,
                    user_id=user_id,
                    command=command,
                    data=data_text
                )
        elif "callback_query" in data:
            callback = data["callback_query"]
            return cls(
                raw_update=raw_update,
                message_type=MessageType.CALLBACK_QUERY,
                chat_id=callback["message"]["chat"]["id"],
                user_id=callback["from"]["id"],
                command=None,
                data=callback["data"]
            )
        return cls(
            raw_update=raw_update,
            message_type=MessageType.UNKNOWN,
            chat_id=0,
            user_id=0
        )
