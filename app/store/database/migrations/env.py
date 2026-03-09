import os
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config
from sqlalchemy.pool import NullPool
from dotenv import load_dotenv

# --- НАЧАЛО ИСПРАВЛЕНИЯ ---
# Добавляем корневую директорию проекта в sys.path
# Это позволяет Alembic находить модуль 'app'
# Путь до env.py: /app/store/database/migrations/env.py
# Нам нужно подняться на 4 уровня вверх, чтобы получить корень проекта
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', '..'))
sys.path.insert(0, project_root)
# --- КОНЕЦ ИСПРАВЛЕНИЯ ---

# Загружаем переменные окружения из .env
load_dotenv()

# Импортируем базовые классы моделей, чтобы Alembic их "увидел"
# Важно, чтобы Base был импортирован из каждого модуля, где есть модели
from app.data.models import Base as DataBase
from app.market.models import Base as MarketBase
from app.users.models import Base as UsersBase

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
# --- НАЧАЛО ИСПРАВЛЕНИЯ ---
# Закомментировано, чтобы избежать ошибки KeyError: 'formatters' при отсутствии
# секций логирования в alembic.ini
# if config.config_file_name is not None:
#     fileConfig(config.config_file_name)
# --- КОНЕЦ ИСПРАВЛЕНИЯ ---

# Устанавливаем DSN из переменных окружения
# Это позволяет не хранить его в alembic.ini
db_dsn = os.getenv("DATABASE_DSN")
if not db_dsn:
    raise ValueError("DATABASE_DSN не найден в .env файле!")
config.set_main_option("sqlalchemy.url", db_dsn)


# add your model's MetaData object here
# for 'autogenerate' support
# target_metadata = mymodel.Base.metadata
# Собираем метаданные со всех моделей
target_metadata = [DataBase.metadata, MarketBase.metadata, UsersBase.metadata]

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def run_migrations_offline():
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section),
        prefix="sqlalchemy.",
        poolclass=NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
