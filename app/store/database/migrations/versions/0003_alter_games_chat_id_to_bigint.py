"""alter games chat_id to bigint

Revision ID: 0003_games_chat_bigint
Revises: 0002_sync_current_game_schema
Create Date: 2026-03-14 00:00:01.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "0003_games_chat_bigint"
down_revision: str | Sequence[str] | None = "0002_sync_current_game_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    game_columns = {column["name"]: column for column in inspector.get_columns("games")}
    chat_id_column = game_columns.get("chat_id")
    if chat_id_column is None:
        return

    if isinstance(chat_id_column["type"], sa.Integer) and not isinstance(
        chat_id_column["type"], sa.BigInteger
    ):
        with op.batch_alter_table("games") as batch_op:
            batch_op.alter_column(
                "chat_id",
                existing_type=sa.Integer(),
                type_=sa.BigInteger(),
                postgresql_using="chat_id::bigint",
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    game_columns = {column["name"]: column for column in inspector.get_columns("games")}
    chat_id_column = game_columns.get("chat_id")
    if chat_id_column is None:
        return

    if isinstance(chat_id_column["type"], sa.BigInteger):
        with op.batch_alter_table("games") as batch_op:
            batch_op.alter_column(
                "chat_id",
                existing_type=sa.BigInteger(),
                type_=sa.Integer(),
                postgresql_using="chat_id::integer",
            )
