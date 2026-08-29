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


def upgrade() -> None:
    op.add_column(
        "chat_histories",
        sa.Column(
            "conversation_id",
            sa.String(36),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_chat_histories_conversation_id",
        "chat_histories",
        ["conversation_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_chat_histories_conversation_id", table_name="chat_histories")
    op.drop_column("chat_histories", "conversation_id")