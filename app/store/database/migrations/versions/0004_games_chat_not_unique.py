"""drop unique constraint from games chat_id

Revision ID: 0004_games_chat_not_unique
Revises: 0003_games_chat_bigint
Create Date: 2026-03-14 00:00:02.000000
"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy import inspect

revision: str = "0004_games_chat_not_unique"
down_revision: str | Sequence[str] | None = "0003_games_chat_bigint"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    constraint_names = {
        constraint["name"]
        for constraint in inspector.get_unique_constraints("games")
        if constraint["name"]
    }
    if "games_chat_id_key" in constraint_names:
        op.drop_constraint("games_chat_id_key", "games", type_="unique")


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    constraint_names = {
        constraint["name"]
        for constraint in inspector.get_unique_constraints("games")
        if constraint["name"]
    }
    if "games_chat_id_key" not in constraint_names:
        op.create_unique_constraint("games_chat_id_key", "games", ["chat_id"])
