"""when a candidate's AI-written paper was asked for

A paper that has been `pending` for too long is the candidate's cue to ask again, so the session
remembers when its paper was last asked for (opening the link, or asking again).

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-23 17:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '0011'
down_revision: Union[str, Sequence[str], None] = '0010'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'sessions', sa.Column('paper_requested_at', sa.DateTime(timezone=True), nullable=True)
    )
    # whoever is waiting now has been waiting since they opened their link
    op.execute(
        "update sessions set paper_requested_at = created_at where paper_status = 'pending'"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('sessions', 'paper_requested_at')
