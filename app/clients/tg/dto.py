from dataclasses import dataclass, asdict
from io import BytesIO
from typing import Optional, Dict, Any

# Клавиатуры в Telegram - это JSON-объекты.
# Мы будем представлять их как словари.
Keyboard = Dict[str, Any]


@dataclass
class MessagePayload:
    """
    Объект с данными для отправки нового сообщения.
    """
    chat_id: int
    text: Optional[str] = None
    photo_path: Optional[str] = None  # Путь к файлу на диске
    photo_buffer: Optional[BytesIO] = None
    keyboard: Optional[Keyboard] = None
    message_id: Optional[int] = -1

    def to_dict(self) -> dict:
        """Сериализует объект в словарь, исключая photo_buffer."""
        data = asdict(self)
        del data['photo_buffer']  # BytesIO не сериализуется в JSON
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "MessagePayload":
        """Создает объект из словаря."""
        return cls(**data)
