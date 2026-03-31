"""add users fsm_state json column

Revision ID: 0005_users_fsm_json
Revises: 0004_games_chat_not_unique
Create Date: 2026-03-14 00:00:03.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "0005_users_fsm_json"
down_revision: str | Sequence[str] | None = "0004_games_chat_not_unique"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("users")}
    if "fsm_state" not in columns:
        op.add_column("users", sa.Column("fsm_state", sa.JSON(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("users")}
    if "fsm_state" in columns:
        op.drop_column("users", "fsm_state")
