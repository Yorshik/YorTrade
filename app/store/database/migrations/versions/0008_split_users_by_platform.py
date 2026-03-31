"""split users by platform and remove terminal linking

Revision ID: 0008_split_users_by_platform
Revises: 0007_user_term_game_platform
Create Date: 2026-03-16 22:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "0008_split_users_by_platform"
down_revision: str | Sequence[str] | None = "0007_user_term_game_platform"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_column(inspector, table_name: str, column_name: str) -> bool:
    columns = {column["name"] for column in inspector.get_columns(table_name)}
    return column_name in columns


def _has_unique_constraint(
    inspector, table_name: str, columns: tuple[str, ...]
) -> bool:
    for constraint in inspector.get_unique_constraints(table_name):
        if tuple(constraint.get("column_names") or ()) == columns:
            return True
    for index in inspector.get_indexes(table_name):
        if index.get("unique") and tuple(index.get("column_names") or ()) == columns:
            return True
    return False


def _drop_unique_by_columns(
    inspector, table_name: str, columns: tuple[str, ...]
) -> None:
    dropped_names: set[str] = set()
    for constraint in inspector.get_unique_constraints(table_name):
        name = constraint.get("name")
        if name and tuple(constraint.get("column_names") or ()) == columns:
            op.drop_constraint(name, table_name, type_="unique")
            dropped_names.add(name)
    for index in inspector.get_indexes(table_name):
        if not index.get("unique"):
            continue
        name = index.get("name")
        if not name or name in dropped_names:
            continue
        if tuple(index.get("column_names") or ()) == columns:
            op.drop_index(name, table_name=table_name)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    if _has_column(inspector, "users", "platform") is False:
        op.add_column(
            "users",
            sa.Column("platform", sa.String(), nullable=False, server_default="TG"),
        )

    inspector = inspect(bind)
    _drop_unique_by_columns(inspector, "users", ("tg_user_id",))

    inspector = inspect(bind)
    if _has_unique_constraint(inspector, "users", ("platform", "tg_user_id")) is False:
        op.create_unique_constraint(
            "uq_users_platform_tg_user_id",
            "users",
            ["platform", "tg_user_id"],
        )

    if _has_column(inspector, "users", "fsm_state"):
        op.execute(sa.text("UPDATE users SET fsm_state = NULL"))

    inspector = inspect(bind)
    if _has_column(inspector, "users", "preferred_terminal"):
        op.drop_column("users", "preferred_terminal")

    inspector = inspect(bind)
    if "user_terminals" in set(inspector.get_table_names()):
        op.drop_table("user_terminals")


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    _drop_unique_by_columns(inspector, "users", ("platform", "tg_user_id"))

    inspector = inspect(bind)
    if _has_unique_constraint(inspector, "users", ("tg_user_id",)) is False:
        op.create_unique_constraint("uq_users_tg_user_id", "users", ["tg_user_id"])

    inspector = inspect(bind)
    if "user_terminals" not in set(inspector.get_table_names()):
        op.create_table(
            "user_terminals",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False
            ),
            sa.Column("platform", sa.String(), nullable=False),
            sa.Column("external_user_id", sa.BigInteger(), nullable=False),
            sa.Column("dm_chat_id", sa.BigInteger(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=True,
            ),
            sa.UniqueConstraint(
                "platform",
                "external_user_id",
                name="uq_user_terminals_platform_external",
            ),
            sa.UniqueConstraint(
                "user_id", "platform", name="uq_user_terminals_user_platform"
            ),
        )

    inspector = inspect(bind)
    if _has_column(inspector, "users", "preferred_terminal") is False:
        op.add_column(
            "users",
            sa.Column(
                "preferred_terminal", sa.String(), nullable=False, server_default="TG"
            ),
        )

    inspector = inspect(bind)
    if _has_column(inspector, "users", "platform"):
        op.drop_column("users", "platform")
