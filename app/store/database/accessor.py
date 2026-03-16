import logging

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

logger = logging.getLogger(__name__)


class DatabaseAccessor:
    def __init__(self, dsn: str, echo: bool = False):
        self._engine = create_async_engine(dsn, echo=echo)
        self._session_factory = sessionmaker(
            self._engine, class_=AsyncSession, expire_on_commit=False
        )

    async def connect(self):
        try:
            logger.info("Успешное подключение к базе данных.")
        except Exception as e:
            logger.error(f"Ошибка подключения к базе данных: {e}", exc_info=True)
            raise

    async def disconnect(self):
        if self._engine is not None:
            await self._engine.dispose()
        logger.info("Соединение с базой данных закрыто.")

    @property
    def session(self) -> AsyncSession:
        return self._session_factory()

    async def get_session(self) -> AsyncSession:
        return self._session_factory()
