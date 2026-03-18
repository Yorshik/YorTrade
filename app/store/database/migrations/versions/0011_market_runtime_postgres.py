"""market runtime tables in postgres

Revision ID: 0011_market_runtime_postgres
Revises: 0010_user_achievement_stats
Create Date: 2026-03-18 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql

revision: str = "0011_market_runtime_postgres"
down_revision: str | Sequence[str] | None = "0010_user_achievement_stats"
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

    market_direction_enum = postgresql.ENUM(
        "UP", "DOWN", name="marketdirection", create_type=False
    )
    market_direction_enum.create(bind, checkfirst=True)

    game_assets_columns = _column_names(inspector, "game_assets")
    if "company_id" not in game_assets_columns:
        op.add_column("game_assets", sa.Column("company_id", sa.String(), nullable=True))

    if not _has_table(inspector, "game_runtime_state"):
        op.create_table(
            "game_runtime_state",
            sa.Column("game_id", sa.Integer(), sa.ForeignKey("games.id"), primary_key=True),
            sa.Column("state", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=True,
            ),
        )

    if not _has_table(inspector, "companies"):
        op.create_table(
            "companies",
            sa.Column("game_id", sa.Integer(), sa.ForeignKey("games.id"), primary_key=True),
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("name", sa.String(), nullable=False),
            sa.Column("current_price", sa.Float(), nullable=False),
            sa.Column("volatility", sa.Float(), nullable=False),
        )

    if not _has_table(inspector, "price_history"):
        op.create_table(
            "price_history",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("game_id", sa.Integer(), sa.ForeignKey("games.id"), nullable=False),
            sa.Column("company_id", sa.String(), nullable=False),
            sa.Column("tick", sa.Integer(), nullable=False),
            sa.Column("price", sa.Float(), nullable=False),
        )
        op.create_index(
            "ix_price_history_game_tick",
            "price_history",
            ["game_id", "tick"],
            unique=False,
        )

    if not _has_table(inspector, "event_templates"):
        op.create_table(
            "event_templates",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("title", sa.String(), nullable=False),
            sa.Column("description", sa.String(), nullable=False),
            sa.Column("effects", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
            sa.Column("duration_ticks", sa.Integer(), nullable=False),
            sa.Column("image_id", sa.String(), nullable=True),
        )

    if not _has_table(inspector, "active_events"):
        op.create_table(
            "active_events",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("game_id", sa.Integer(), sa.ForeignKey("games.id"), nullable=False),
            sa.Column("template_id", sa.String(), sa.ForeignKey("event_templates.id"), nullable=False),
            sa.Column("company_id", sa.String(), nullable=True),
            sa.Column("strength", sa.Float(), nullable=False, server_default=sa.text("0.0")),
            sa.Column("start_tick", sa.Integer(), nullable=False),
            sa.Column("end_tick", sa.Integer(), nullable=False),
            sa.Column("meta", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        )
        op.create_index(
            "ix_active_events_game_tick",
            "active_events",
            ["game_id", "start_tick", "end_tick"],
            unique=False,
        )

    if not _has_table(inspector, "news"):
        op.create_table(
            "news",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("game_id", sa.Integer(), sa.ForeignKey("games.id"), nullable=False),
            sa.Column("company_id", sa.String(), nullable=False),
            sa.Column("direction", market_direction_enum, nullable=False),
            sa.Column("strength", sa.Float(), nullable=False),
            sa.Column("tick", sa.Integer(), nullable=False),
        )
        op.create_index("ix_news_game_tick", "news", ["game_id", "tick"], unique=False)

    if not _has_table(inspector, "insider_info"):
        op.create_table(
            "insider_info",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("game_id", sa.Integer(), sa.ForeignKey("games.id"), nullable=False),
            sa.Column("company_id", sa.String(), nullable=False),
            sa.Column("direction", market_direction_enum, nullable=False),
            sa.Column("strength", sa.Float(), nullable=False),
            sa.Column("target_tick", sa.Integer(), nullable=False),
            sa.Column("is_true", sa.Boolean(), nullable=False),
        )
        op.create_index(
            "ix_insider_info_game_tick",
            "insider_info",
            ["game_id", "target_tick"],
            unique=False,
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    if _has_table(inspector, "insider_info"):
        op.drop_index("ix_insider_info_game_tick", table_name="insider_info")
        op.drop_table("insider_info")

    if _has_table(inspector, "news"):
        op.drop_index("ix_news_game_tick", table_name="news")
        op.drop_table("news")

    if _has_table(inspector, "active_events"):
        op.drop_index("ix_active_events_game_tick", table_name="active_events")
        op.drop_table("active_events")

    if _has_table(inspector, "event_templates"):
        op.drop_table("event_templates")

    if _has_table(inspector, "price_history"):
        op.drop_index("ix_price_history_game_tick", table_name="price_history")
        op.drop_table("price_history")

    if _has_table(inspector, "companies"):
        op.drop_table("companies")

    if _has_table(inspector, "game_runtime_state"):
        op.drop_table("game_runtime_state")

    game_assets_columns = _column_names(inspector, "game_assets")
    if "company_id" in game_assets_columns:
        op.drop_column("game_assets", "company_id")

    market_direction_enum = postgresql.ENUM(
        "UP", "DOWN", name="marketdirection", create_type=False
    )
    market_direction_enum.drop(bind, checkfirst=True)
