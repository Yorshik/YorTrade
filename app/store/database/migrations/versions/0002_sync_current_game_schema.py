"""sync current game schema

Revision ID: 0002_sync_current_game_schema
Revises: 0001_initial_schema
Create Date: 2026-03-14 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "0002_sync_current_game_schema"
down_revision: str | Sequence[str] | None = "0001_initial_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_table(inspector, table_name: str) -> bool:
    return table_name in inspector.get_table_names()


def _column_names(inspector, table_name: str) -> set[str]:
    if not _has_table(inspector, table_name):
        return set()
    return {column["name"] for column in inspector.get_columns(table_name)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    user_columns = _column_names(inspector, "users")
    if "dm_chat_id" not in user_columns:
        op.add_column("users", sa.Column("dm_chat_id", sa.BigInteger(), nullable=True))

    if not _has_table(inspector, "players"):
        op.create_table(
            "players",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False
            ),
            sa.Column(
                "game_id", sa.Integer(), sa.ForeignKey("games.id"), nullable=False
            ),
            sa.Column("balance", sa.Float(), nullable=False, server_default="1000"),
            sa.Column(
                "is_active", sa.Boolean(), nullable=False, server_default=sa.true()
            ),
            sa.Column(
                "update_mode", sa.String(), nullable=False, server_default="server"
            ),
            sa.Column("final_capital", sa.Float(), nullable=True),
            sa.Column(
                "joined_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=True,
            ),
            sa.Column("left_at", sa.DateTime(timezone=True), nullable=True),
        )

    game_asset_columns = _column_names(inspector, "game_assets")
    if "shares_total" not in game_asset_columns:
        op.add_column(
            "game_assets",
            sa.Column(
                "shares_total", sa.Integer(), nullable=False, server_default="1000"
            ),
        )
    if "shares_available" not in game_asset_columns:
        op.add_column(
            "game_assets",
            sa.Column(
                "shares_available", sa.Integer(), nullable=False, server_default="1000"
            ),
        )

    deal_columns = _column_names(inspector, "deals")
    if "user_id" in deal_columns and "player_id" not in deal_columns:
        op.drop_table("deals")
        op.create_table(
            "deals",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "player_id", sa.Integer(), sa.ForeignKey("players.id"), nullable=False
            ),
            sa.Column(
                "game_id", sa.Integer(), sa.ForeignKey("games.id"), nullable=False
            ),
            sa.Column(
                "asset_id", sa.Integer(), sa.ForeignKey("assets.id"), nullable=False
            ),
            sa.Column(
                "type",
                sa.Enum("BUY", "SELL", name="dealtype", create_type=False),
                nullable=False,
            ),
            sa.Column("amount", sa.Integer(), nullable=False),
            sa.Column("price", sa.Float(), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=True,
            ),
        )

    portfolio_columns = _column_names(inspector, "portfolios")
    if "user_id" in portfolio_columns and "player_id" not in portfolio_columns:
        op.drop_table("portfolios")
        op.create_table(
            "portfolios",
            sa.Column(
                "player_id", sa.Integer(), sa.ForeignKey("players.id"), primary_key=True
            ),
            sa.Column(
                "asset_id", sa.Integer(), sa.ForeignKey("assets.id"), primary_key=True
            ),
            sa.Column("amount", sa.Integer(), nullable=False),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    portfolio_columns = _column_names(inspector, "portfolios")
    if "player_id" in portfolio_columns and "user_id" not in portfolio_columns:
        op.drop_table("portfolios")
        op.create_table(
            "portfolios",
            sa.Column(
                "user_id", sa.Integer(), sa.ForeignKey("users.id"), primary_key=True
            ),
            sa.Column(
                "asset_id", sa.Integer(), sa.ForeignKey("assets.id"), primary_key=True
            ),
            sa.Column("amount", sa.Integer(), nullable=False),
        )

    deal_columns = _column_names(inspector, "deals")
    if "player_id" in deal_columns and "user_id" not in deal_columns:
        op.drop_table("deals")
        op.create_table(
            "deals",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False
            ),
            sa.Column(
                "game_id", sa.Integer(), sa.ForeignKey("games.id"), nullable=False
            ),
            sa.Column(
                "asset_id", sa.Integer(), sa.ForeignKey("assets.id"), nullable=False
            ),
            sa.Column(
                "type",
                sa.Enum("BUY", "SELL", name="dealtype", create_type=False),
                nullable=False,
            ),
            sa.Column("amount", sa.Integer(), nullable=False),
            sa.Column("price", sa.Float(), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=True,
            ),
        )

    game_asset_columns = _column_names(inspector, "game_assets")
    if "shares_available" in game_asset_columns:
        op.drop_column("game_assets", "shares_available")
    if "shares_total" in game_asset_columns:
        op.drop_column("game_assets", "shares_total")

    if _has_table(inspector, "players"):
        op.drop_table("players")

    user_columns = _column_names(inspector, "users")
    if "dm_chat_id" in user_columns:
        op.drop_column("users", "dm_chat_id")
