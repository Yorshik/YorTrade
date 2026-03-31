"""initial schema

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-03-13 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial_schema"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


game_status_enum = postgresql.ENUM(
    "PENDING", "ACTIVE", "FINISHED", name="gamestatus", create_type=False
)
deal_type_enum = postgresql.ENUM("BUY", "SELL", name="dealtype", create_type=False)
phrase_type_enum = postgresql.ENUM(
    "GROWTH", "STABLE", "FALL", name="phrasetype", create_type=False
)


def upgrade() -> None:
    bind = op.get_bind()
    game_status_enum.create(bind, checkfirst=True)
    deal_type_enum.create(bind, checkfirst=True)
    phrase_type_enum.create(bind, checkfirst=True)

    op.create_table(
        "games",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("host_id", sa.BigInteger(), nullable=False),
        sa.Column("status", game_status_enum, nullable=False),
        sa.Column("settings", sa.JSON(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tg_user_id", sa.BigInteger(), nullable=False, unique=True),
        sa.Column("username", sa.String(), nullable=True),
        sa.Column("dm_chat_id", sa.BigInteger(), nullable=True),
        sa.Column("fsm_state", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
        ),
    )

    op.create_table(
        "assets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("base_volatility", sa.Float(), nullable=False),
    )

    op.create_table(
        "phrases",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("type", phrase_type_enum, nullable=False),
        sa.Column("phrase", sa.String(), nullable=False),
        sa.Column("asset_id", sa.Integer(), sa.ForeignKey("assets.id"), nullable=True),
    )

    op.create_table(
        "players",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("game_id", sa.Integer(), sa.ForeignKey("games.id"), nullable=False),
        sa.Column("balance", sa.Float(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("update_mode", sa.String(), nullable=False),
        sa.Column("final_capital", sa.Float(), nullable=True),
        sa.Column(
            "joined_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
        ),
        sa.Column("left_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "deals",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "player_id", sa.Integer(), sa.ForeignKey("players.id"), nullable=False
        ),
        sa.Column("game_id", sa.Integer(), sa.ForeignKey("games.id"), nullable=False),
        sa.Column("asset_id", sa.Integer(), sa.ForeignKey("assets.id"), nullable=False),
        sa.Column("type", deal_type_enum, nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("price", sa.Float(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
        ),
    )

    op.create_table(
        "game_assets",
        sa.Column("game_id", sa.Integer(), sa.ForeignKey("games.id"), primary_key=True),
        sa.Column(
            "asset_id", sa.Integer(), sa.ForeignKey("assets.id"), primary_key=True
        ),
        sa.Column("start_price", sa.Float(), nullable=False),
        sa.Column("volatility", sa.Float(), nullable=False),
        sa.Column("shares_total", sa.Integer(), nullable=False),
        sa.Column("shares_available", sa.Integer(), nullable=False),
    )

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
    op.drop_table("portfolios")
    op.drop_table("game_assets")
    op.drop_table("deals")
    op.drop_table("players")
    op.drop_table("phrases")
    op.drop_table("assets")
    op.drop_table("users")
    op.drop_table("games")

    bind = op.get_bind()
    phrase_type_enum.drop(bind, checkfirst=True)
    deal_type_enum.drop(bind, checkfirst=True)
    game_status_enum.drop(bind, checkfirst=True)
