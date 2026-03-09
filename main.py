import os
import asyncio
import logging
import aiohttp
from dotenv import load_dotenv
from aiohttp.web import Application

from app.store.queue.accessor import RabbitMQAccessor
from app.store.cache.accessor import RedisAccessor
from app.store.database.accessor import DatabaseAccessor
from app.clients.tg.poller import Poller
from app.clients.tg.sender import Sender
from app.clients.tg.handlers import (
    HandlerFactory, PingHandler, NewChatMemberHandler, 
    StartCycleHandler, StopCycleHandler
)
from app.clients.tg.worker import Worker
from app.game.engine import GameEngine


def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
    )


async def setup_session(app: Application):
    session = aiohttp.ClientSession()
    app["session"] = session
    app.on_cleanup.append(session.close)


async def setup_rabbit(app: Application):
    rabbit_dsn = os.getenv("RABBITMQ_DSN", "amqp://guest:guest@localhost/")
    rabbitmq = RabbitMQAccessor(dsn=rabbit_dsn)
    await rabbitmq.connect()
    app["rabbitmq"] = rabbitmq
    app.on_cleanup.append(lambda: rabbitmq.disconnect())


async def setup_redis(app: Application):
    redis_dsn = os.getenv("REDIS_DSN", "redis://localhost:6379/0")
    redis_accessor = RedisAccessor(dsn=redis_dsn)
    await redis_accessor.connect()
    app["redis"] = redis_accessor
    app.on_cleanup.append(redis_accessor.disconnect)


async def setup_database(app: Application):
    db_dsn = os.getenv("DATABASE_DSN", "postgresql+asyncpg://user:password@localhost/dbname")
    db_accessor = DatabaseAccessor(dsn=db_dsn)
    await db_accessor.connect()
    app["db"] = db_accessor
    app.on_cleanup.append(db_accessor.disconnect)


async def setup_game_engine(app: Application):
    engine = GameEngine(app)
    app["game_engine"] = engine
    app.on_shutdown.append(engine.stop_all_cycles)


async def setup_handlers(app: Application):
    factory = HandlerFactory(app)
    factory.add_handler(PingHandler)
    factory.add_handler(NewChatMemberHandler)
    factory.add_handler(StartCycleHandler)
    factory.add_handler(StopCycleHandler)
    app["handler_factory"] = factory


async def setup_telegram_components(app: Application):
    app["sender"] = Sender(app)
    app["poller"] = Poller(app)
    app["worker"] = Worker(app)
    app.on_shutdown.append(app["poller"].stop)
    app.on_shutdown.append(app["worker"].stop)
    app.on_shutdown.append(app["sender"].stop)


async def main():
    load_dotenv()
    setup_logging()
    
    app = Application()
    bot_token = os.getenv("BOT_TOKEN")
    if not bot_token:
        raise ValueError("BOT_TOKEN не найден!")
    app["bot_token"] = bot_token
    
    await setup_session(app)
    await setup_rabbit(app)
    await setup_redis(app)
    await setup_database(app)
    await setup_handlers(app)
    await setup_telegram_components(app)
    await setup_game_engine(app)

    logging.info("Приложение запущено. Ctrl+C для остановки.")
    asyncio.create_task(app["poller"].start())
    asyncio.create_task(app["worker"].start())
    asyncio.create_task(app["sender"].start())

    try:
        await asyncio.Event().wait()
    finally:
        await app.shutdown()
        await app.cleanup()
        logging.info("Приложение остановлено.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("Приложение принудительно остановлено.")
