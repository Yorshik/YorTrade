import json
import logging
from typing import Optional, Any
import redis.asyncio as redis

logger = logging.getLogger(__name__)


class RedisAccessor:
    def __init__(self, dsn: str):
        self.dsn = dsn
        self.redis: Optional[redis.Redis] = None

    async def connect(self):
        try:
            self.redis = redis.from_url(self.dsn, decode_responses=True)
            await self.redis.ping()
            logger.info("Успешное подключение к Redis")
        except Exception as e:
            logger.error(f"Ошибка подключения к Redis: {e}", exc_info=True)
            raise

    async def disconnect(self):
        if self.redis:
            await self.redis.close()
            logger.info("Соединение с Redis закрыто")

    async def get(self, key: str) -> Optional[str]:
        if not self.redis:
            return None
        return await self.redis.get(key)

    async def set(self, key: str, value: Any, expires_in: Optional[int] = None):
        if not self.redis:
            return
        await self.redis.set(key, value, ex=expires_in)

    async def set_if_absent(self, key: str, value: Any, expires_in: Optional[int] = None) -> bool:
        if not self.redis:
            return False
        return bool(await self.redis.set(key, value, ex=expires_in, nx=True))

    async def delete(self, key: str):
        if not self.redis:
            return
        await self.redis.delete(key)

    async def set_message_info(self, chat_id: int, message_id: int):
        key = f"last_message:{chat_id}"
        value = json.dumps({"chat_id": chat_id, "message_id": message_id})
        await self.set(key, value, expires_in=60 * 60 * 24 * 7)

    async def get_message_info(self, chat_id: int):
        key = f"last_message:{chat_id}"
        result = await self.get(key)
        if not result:
            return -1
        return json.loads(result)["message_id"]
