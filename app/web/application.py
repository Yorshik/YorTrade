import logging
from typing import Any

import aiohttp
from aiohttp.web_app import Application

from app.api.admin import ensure_bootstrap_admin, setup_admin_api
from app.clients.common.handler_factory import HandlerFactory
from app.clients.common.sender_router import SenderRouter
from app.market.engine import GameEngine
from app.store.cache.accessor import RedisAccessor
from app.store.data.accessor import DataAccessor
from app.store.database.accessor import DatabaseAccessor
from app.store.fsm.accessor import FSMAccessor
from app.store.market.accessor import MarketAccessor
from app.store.queue.accessor import RabbitMQAccessor
from app.store.users.accessor import UserAccessor
from app.utils.data_loader import ensure_server_data_loaded
from app.web.config import Config
from app.web.logger import setup_logging
from app.web.middleware_factory import MiddlewareFactory
from app.web.middlewares.callback_sanity_middleware import CallbackSanityMiddleware
from app.web.middlewares.dedup_middleware import DedupMiddleware
from app.web.middlewares.game_access_middleware import GameAccessMiddleware
from app.web.middlewares.maintenance_middleware import MaintenanceMiddleware
from app.web.middlewares.rate_limit_middleware import RateLimitMiddleware
from app.web.middlewares.user_middleware import UserMiddleware

logger = logging.getLogger(__name__)


class App(Application):
    fsm: FSMAccessor | None = None
    config: Config | None = None
    session: aiohttp.ClientSession | None = None
    rabbitmq: RabbitMQAccessor | None = None
    redis: RedisAccessor | None = None
    db: DatabaseAccessor | None = None
    users: UserAccessor | None = None
    data: DataAccessor | None = None
    market: MarketAccessor | None = None
    sender: Any | None = None
    poller: Any | None = None
    worker: Any | None = None
    handler_factory: HandlerFactory | None = None
    middleware_factory: MiddlewareFactory | None = None
    game_engine: GameEngine | None = None


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
    app.fsm = FSMAccessor(app)
    yield
    await app.redis.disconnect()


async def setup_database(app: App):
    app.db = DatabaseAccessor(dsn=app.config.DATABASE_DSN)
    await app.db.connect()
    app.users = UserAccessor(app.db)
    app.data = DataAccessor(app.db)
    app.market = MarketAccessor(app.db)
    await ensure_bootstrap_admin(app)
    bootstrap_stats = await ensure_server_data_loaded(app)
    if int(bootstrap_stats.get("skipped", 0)):
        logger.info("Server data bootstrap skipped: catalog already loaded.")
    else:
        logger.info(
            "Server data bootstrap completed assets_created=%s phrases_created=%s templates_loaded=%s news_loaded=%s",
            bootstrap_stats.get("assets_created", 0),
            bootstrap_stats.get("phrases_created", 0),
            bootstrap_stats.get("event_templates_loaded", 0),
            bootstrap_stats.get("news_loaded", 0),
        )
    yield
    await app.db.disconnect()


def _resolve_client_components():
    from app.clients.tg.poller import Poller as TgPoller
    from app.clients.tg.sender import Sender as TgSender
    from app.clients.tg.worker import Worker as TgWorker
    from app.clients.vk.poller import Poller as VkPoller
    from app.clients.vk.sender import Sender as VkSender
    from app.clients.vk.worker import Worker as VkWorker

    return TgPoller, TgSender, TgWorker, VkPoller, VkSender, VkWorker


async def setup_client_components(app: App):
    (
        tg_poller_cls,
        tg_sender_cls,
        tg_worker_cls,
        vk_poller_cls,
        vk_sender_cls,
        vk_worker_cls,
    ) = _resolve_client_components()
    logger.info("Bootstrapping dual client transport tg+vk")

    tg_enabled = bool((app.config.TG_TOKEN or "").strip())
    vk_enabled = (
        bool((app.config.VK_TOKEN or "").strip())
        and int(app.config.VK_GROUP_ID or 0) > 0
    )

    tg_sender = tg_sender_cls(app) if tg_enabled else None
    vk_sender = vk_sender_cls(app) if vk_enabled else None
    tg_poller = tg_poller_cls(app) if tg_enabled else None
    vk_poller = vk_poller_cls(app) if vk_enabled else None
    tg_worker = tg_worker_cls(app) if tg_enabled else None
    vk_worker = vk_worker_cls(app) if vk_enabled else None

    app.sender = SenderRouter(tg_sender=tg_sender, vk_sender=vk_sender)
    app.poller = [
        component for component in [tg_poller, vk_poller] if component is not None
    ]
    app.worker = [
        component for component in [tg_worker, vk_worker] if component is not None
    ]

    if tg_sender:
        await tg_sender.start()
    if vk_sender:
        await vk_sender.start()
    if tg_poller:
        await tg_poller.start()
    if vk_poller:
        await vk_poller.start()
    if tg_worker:
        await tg_worker.start()
    if vk_worker:
        await vk_worker.start()

    yield

    if tg_worker:
        await tg_worker.stop()
    if vk_worker:
        await vk_worker.stop()
    if tg_poller:
        await tg_poller.stop()
    if vk_poller:
        await vk_poller.stop()
    if tg_sender:
        await tg_sender.stop()
    if vk_sender:
        await vk_sender.stop()


async def setup_game_engine(app: App):
    yield
    await app.game_engine.stop_all_games()


def setup_app(config_path: str) -> App:
    setup_logging()

    app = App()
    app.config = Config(_env_file=config_path)

    app.game_engine = GameEngine(app)
    app.handler_factory = HandlerFactory(app)
    app.middleware_factory = MiddlewareFactory(
        app,
        [
            MaintenanceMiddleware(),
            DedupMiddleware(),
            UserMiddleware(),
            RateLimitMiddleware(),
            GameAccessMiddleware(),
            CallbackSanityMiddleware(),
        ],
    )

    app.cleanup_ctx.append(setup_session)
    app.cleanup_ctx.append(setup_rabbit)
    app.cleanup_ctx.append(setup_redis)
    app.cleanup_ctx.append(setup_database)
    app.cleanup_ctx.append(setup_client_components)
    app.cleanup_ctx.append(setup_game_engine)
    setup_admin_api(app)

    return app
