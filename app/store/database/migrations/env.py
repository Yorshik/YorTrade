import asyncio
import os
import sys

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
sys.path.insert(0, project_root)

from app.data.models import Asset, Phrase  # noqa: F401
from app.market.models import Deal, Game, GameAsset, Portfolio  # noqa: F401
from app.api.models import ApiAuthSession, ApiAuthUser  # noqa: F401
from app.store.database.base import Base
from app.users.models import Player, User  # noqa: F401

target_metadata = Base.metadata
db_dsn = os.getenv("DATABASE_DSN", "postgresql+asyncpg://postgres:postgres@localhost:5432/app")


def do_run_migrations(connection):
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    async def run():
        connectable = create_async_engine(db_dsn, poolclass=NullPool)
        async with connectable.begin() as conn:
            await conn.run_sync(do_run_migrations)
        await connectable.dispose()

    asyncio.run(run())


def run_migrations_offline():
    url = db_dsn.replace("+asyncpg", "")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
