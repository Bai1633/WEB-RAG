"""Add conversation_id to chat_histories

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-20
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_exists(bind, table_name: str, column_name: str) -> bool:
    """Check whether a column already exists (idempotent migration support)."""
    return (
        bind.execute(
            sa.text(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_name = :tname AND column_name = :cname"
            ),
            {"tname": table_name, "cname": column_name},
        ).scalar()
        is not None
    )


def _index_exists(bind, index_name: str) -> bool:
    """Check whether an index already exists (idempotent migration support)."""
    return (
        bind.execute(
            sa.text("SELECT 1 FROM pg_indexes WHERE indexname = :iname"),
            {"iname": index_name},
        ).scalar()
        is not None
    )


def upgrade() -> None:
    # NOTE: 0001_initial_schema already creates this column/index on a fresh
    # database, so a plain add_column here fails with DuplicateColumn and
    # short-circuits `alembic upgrade head && gunicorn ...` in docker-compose.
    # Make the migration idempotent so both fresh and legacy databases work.
    bind = op.get_bind()

    if not _column_exists(bind, "chat_histories", "conversation_id"):
        op.add_column(
            "chat_histories",
            sa.Column(
                "conversation_id",
                sa.String(36),
                nullable=True,
            ),
        )

    if not _index_exists(bind, "ix_chat_histories_conversation_id"):
        op.create_index(
            "ix_chat_histories_conversation_id",
            "chat_histories",
            ["conversation_id"],
        )


def downgrade() -> None:
    bind = op.get_bind()

    if _index_exists(bind, "ix_chat_histories_conversation_id"):
        op.drop_index("ix_chat_histories_conversation_id", table_name="chat_histories")

    if _column_exists(bind, "chat_histories", "conversation_id"):
        op.drop_column("chat_histories", "conversation_id")