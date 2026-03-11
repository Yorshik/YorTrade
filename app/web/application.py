import logging
from typing import Optional
import aiohttp
from aiohttp.web_app import Application

from app.store.queue.accessor import RabbitMQAccessor
from app.store.cache.accessor import RedisAccessor
from app.store.database.accessor import DatabaseAccessor
from app.clients.tg.poller import Poller
from app.clients.tg.sender import Sender
from app.clients.tg.handler_factory import HandlerFactory
from app.clients.tg.worker import Worker
from app.game.engine import GameEngine
from app.web.config import Config
from app.web.logger import setup_logging


class App(Application):
    config: Optional[Config] = None
    session: Optional[aiohttp.ClientSession] = None
    rabbitmq: Optional[RabbitMQAccessor] = None
    redis: Optional[RedisAccessor] = None
    db: Optional[DatabaseAccessor] = None
    sender: Optional[Sender] = None
    poller: Optional[Poller] = None
    worker: Optional[Worker] = None
    handler_factory: Optional[HandlerFactory] = None
    game_engine: Optional[GameEngine] = None


async def setup_session(app: App):
    app.session = aiohttp.ClientSession()
    yield
    await app.session.close()


async def setup_rabbit(app: App):
    app.rabbitmq = RabbitMQAccessor(dsn=app.config.RABBIT_DSN)
    await app.rabbitmq.connect()
    yield
    await app.rabbitmq.disconnect()


async def setup_redis(app: App):
    app.redis = RedisAccessor(dsn=app.config.REDIS_DSN)
    await app.redis.connect()
    yield
    await app.redis.disconnect()


async def setup_database(app: App):
    app.db = DatabaseAccessor(dsn=app.config.DATABASE_DSN)
    await app.db.connect()
    yield
    await app.db.disconnect()


async def setup_telegram_components(app: App):
    app.sender = Sender(app)
    app.poller = Poller(app)
    app.worker = Worker(app)
    
    await app.sender.start()
    await app.poller.start()
    await app.worker.start()
    
    yield
    
    await app.sender.stop()
    await app.poller.stop()
    await app.worker.stop()


def setup_app(config_path: str) -> App:
    setup_logging()
    
    app = App()
    app.config = Config(_env_file=config_path)

    app.game_engine = GameEngine(app)
    app.handler_factory = HandlerFactory(app)

    app.cleanup_ctx.append(setup_session)
    app.cleanup_ctx.append(setup_rabbit)
    app.cleanup_ctx.append(setup_redis)
    app.cleanup_ctx.append(setup_database)
    app.cleanup_ctx.append(setup_telegram_components)

    return app
