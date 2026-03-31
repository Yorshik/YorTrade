"""add api auth users and sessions

Revision ID: 0009_api_auth_users_sessions
Revises: 0008_split_users_by_platform
Create Date: 2026-03-17 00:25:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "0009_api_auth_users_sessions"
down_revision: str | Sequence[str] | None = "0008_split_users_by_platform"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())

    if "api_auth_users" not in tables:
        op.create_table(
            "api_auth_users",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("username", sa.String(), nullable=False, unique=True),
            sa.Column("password_hash", sa.String(), nullable=False),
            sa.Column(
                "is_staff", sa.Boolean(), nullable=False, server_default=sa.false()
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=True,
            ),
        )

    inspector = inspect(bind)
    tables = set(inspector.get_table_names())
    if "api_auth_sessions" not in tables:
        op.create_table(
            "api_auth_sessions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "user_id",
                sa.Integer(),
                sa.ForeignKey("api_auth_users.id"),
                nullable=False,
            ),
            sa.Column("token", sa.String(), nullable=False, unique=True),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=True,
            ),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())

    if "api_auth_sessions" in tables:
        op.drop_table("api_auth_sessions")

    inspector = inspect(bind)
    tables = set(inspector.get_table_names())
    if "api_auth_users" in tables:
        op.drop_table("api_auth_users")
