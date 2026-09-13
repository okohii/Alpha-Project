"""Add confidence and expiration to memories.

Revision ID: 20260912_01
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260912_01"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("memories")}
    if "confidence" not in columns:
        op.add_column("memories", sa.Column("confidence", sa.Float(), nullable=False, server_default="1.0"))
    if "expiration" not in columns:
        op.add_column("memories", sa.Column("expiration", sa.DateTime(timezone=True), nullable=True))
        op.create_index("ix_memories_expiration", "memories", ["expiration"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    indexes = {index["name"] for index in inspector.get_indexes("memories")}
    if "ix_memories_expiration" in indexes:
        op.drop_index("ix_memories_expiration", table_name="memories")
    columns = {column["name"] for column in inspector.get_columns("memories")}
    if "expiration" in columns:
        op.drop_column("memories", "expiration")
    if "confidence" in columns:
        op.drop_column("memories", "confidence")
