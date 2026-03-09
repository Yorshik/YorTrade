import logging
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from typing import Optional

logger = logging.getLogger(__name__)


class DatabaseAccessor:
    def __init__(self, dsn: str, echo: bool = False):
        self._engine = create_async_engine(dsn, echo=echo)
        self._session_factory = sessionmaker(
            self._engine, class_=AsyncSession, expire_on_commit=False
        )
        self.session: Optional[AsyncSession] = None

    async def connect(self):
        if self.session is not None:
            return
        
        try:
            self.session = self._session_factory()
            logger.info("Успешное подключение к базе данных.")
        except Exception as e:
            logger.error(f"Ошибка подключения к базе данных: {e}", exc_info=True)
            raise

    async def disconnect(self):
        if self.session is not None:
            await self.session.close()
            self.session = None
        if self._engine is not None:
            await self._engine.dispose()
        logger.info("Соединение с базой данных закрыто.")

    async def get_session(self) -> AsyncSession:
        if self.session is None:
            await self.connect()
        return self.session
