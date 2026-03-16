"""drop sectors model and references

Revision ID: 0006_drop_sectors
Revises: 0005_users_fsm_json
Create Date: 2026-03-15 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "0006_drop_sectors"
down_revision: str | Sequence[str] | None = "0005_users_fsm_json"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_table(inspector, table_name: str) -> bool:
    return table_name in inspector.get_table_names()


def _column_names(inspector, table_name: str) -> set[str]:
    if not _has_table(inspector, table_name):
        return set()
    return {column["name"] for column in inspector.get_columns(table_name)}


def _drop_foreign_keys_for_column(inspector, table_name: str, column_name: str) -> None:
    for fk in inspector.get_foreign_keys(table_name):
        constrained_columns = fk.get("constrained_columns") or []
        fk_name = fk.get("name")
        if fk_name and column_name in constrained_columns:
            op.drop_constraint(fk_name, table_name, type_="foreignkey")


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    asset_columns = _column_names(inspector, "assets")
    if "sector_id" in asset_columns:
        _drop_foreign_keys_for_column(inspector, "assets", "sector_id")
        op.drop_column("assets", "sector_id")

    phrase_columns = _column_names(inspector, "phrases")
    if "sector_id" in phrase_columns:
        _drop_foreign_keys_for_column(inspector, "phrases", "sector_id")
        op.drop_column("phrases", "sector_id")

    if _has_table(inspector, "sectors"):
        op.drop_table("sectors")


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    if not _has_table(inspector, "sectors"):
        op.create_table(
            "sectors",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("name", sa.String(), nullable=False, unique=True),
        )

    asset_columns = _column_names(inspector, "assets")
    if "sector_id" not in asset_columns:
        op.add_column("assets", sa.Column("sector_id", sa.Integer(), nullable=True))
        op.create_foreign_key(None, "assets", "sectors", ["sector_id"], ["id"])

    phrase_columns = _column_names(inspector, "phrases")
    if "sector_id" not in phrase_columns:
        op.add_column("phrases", sa.Column("sector_id", sa.Integer(), nullable=True))
        op.create_foreign_key(None, "phrases", "sectors", ["sector_id"], ["id"])
