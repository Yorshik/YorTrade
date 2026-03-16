"""add user achievement stats table

Revision ID: 0010_user_achievement_stats
Revises: 0009_api_auth_users_sessions
Create Date: 2026-03-17 02:10:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "0010_user_achievement_stats"
down_revision: str | Sequence[str] | None = "0009_api_auth_users_sessions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())

    if "user_achievement_stats" not in tables:
        op.create_table(
            "user_achievement_stats",
            sa.Column(
                "user_id", sa.Integer(), sa.ForeignKey("users.id"), primary_key=True
            ),
            sa.Column(
                "capital_growth_peak_ratio",
                sa.Float(),
                nullable=False,
                server_default=sa.text("1.0"),
            ),
            sa.Column(
                "deals_total", sa.Integer(), nullable=False, server_default=sa.text("0")
            ),
            sa.Column(
                "trades_per_tick_peak",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("0"),
            ),
            sa.Column(
                "deal_profit_peak",
                sa.Float(),
                nullable=False,
                server_default=sa.text("0.0"),
            ),
            sa.Column(
                "dividends_total",
                sa.Float(),
                nullable=False,
                server_default=sa.text("0.0"),
            ),
            sa.Column(
                "impact_peak_percent",
                sa.Float(),
                nullable=False,
                server_default=sa.text("0.0"),
            ),
            sa.Column(
                "portfolio_unique_peak",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("0"),
            ),
            sa.Column(
                "portfolio_total_amount_peak",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("0"),
            ),
            sa.Column(
                "wins_total", sa.Integer(), nullable=False, server_default=sa.text("0")
            ),
            sa.Column(
                "company_share_peak_percent",
                sa.Float(),
                nullable=False,
                server_default=sa.text("0.0"),
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=True,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=True,
            ),
            sa.UniqueConstraint("user_id", name="uq_user_achievement_stats_user_id"),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())

    if "user_achievement_stats" in tables:
        op.drop_table("user_achievement_stats")
