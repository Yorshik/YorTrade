import json
from typing import Optional
import redis.asyncio as redis


class RedisAccessor:
    def __init__(self, dsn: str):
        self.dsn = dsn
        self.redis: Optional[redis.Redis] = None

    async def connect(self):
        try:
            self.redis = redis.from_url(self.dsn, decode_responses=True)
            await self.redis.ping()
            print("Успешное подключение к Redis")
        except Exception as e:
            print(f"Ошибка подключения к Redis: {e}")
            raise

    async def disconnect(self):
        if self.redis:
            await self.redis.close()
            print("Соединение с Redis закрыто")

    async def set_message_info(self, chat_id: int, message_id: int):
        """
        Сохраняет информацию о последнем отправленном сообщении для данного чата.
        """
        if not self.redis:
            return

        key = f"last_message:{chat_id}"
        value = json.dumps({"chat_id": chat_id, "message_id": message_id})
        await self.redis.set(key, value, ex=60 * 60 * 24 * 7)

    async def get_message_info(self, chat_id: int):
        if not self.redis:
            return -1

        key = f"last_message:{chat_id}"
        result = await self.redis.get(key)
        if not result:
            return -1
        return json.loads(result)["message_id"]