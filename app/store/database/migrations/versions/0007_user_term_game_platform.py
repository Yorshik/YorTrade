"""add user terminals and game platform

Revision ID: 0007_user_term_game_platform
Revises: 0006_drop_sectors
Create Date: 2026-03-16 04:10:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = "0007_user_term_game_platform"
down_revision: Union[str, Sequence[str], None] = "0006_drop_sectors"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(inspector, table_name: str, column_name: str) -> bool:
    columns = {column["name"] for column in inspector.get_columns(table_name)}
    return column_name in columns


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    if _has_column(inspector, "users", "preferred_terminal") is False:
        op.add_column(
            "users",
            sa.Column("preferred_terminal", sa.String(), nullable=False, server_default="TG"),
        )

    inspector = inspect(bind)
    if _has_column(inspector, "games", "platform") is False:
        op.add_column(
            "games",
            sa.Column("platform", sa.String(), nullable=False, server_default="TG"),
        )

    if "user_terminals" not in set(inspector.get_table_names()):
        op.create_table(
            "user_terminals",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("platform", sa.String(), nullable=False),
            sa.Column("external_user_id", sa.BigInteger(), nullable=False),
            sa.Column("dm_chat_id", sa.BigInteger(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
            sa.UniqueConstraint("platform", "external_user_id", name="uq_user_terminals_platform_external"),
            sa.UniqueConstraint("user_id", "platform", name="uq_user_terminals_user_platform"),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    if "user_terminals" in set(inspector.get_table_names()):
        op.drop_table("user_terminals")

    inspector = inspect(bind)
    if _has_column(inspector, "games", "platform"):
        op.drop_column("games", "platform")

    inspector = inspect(bind)
    if _has_column(inspector, "users", "preferred_terminal"):
        op.drop_column("users", "preferred_terminal")
