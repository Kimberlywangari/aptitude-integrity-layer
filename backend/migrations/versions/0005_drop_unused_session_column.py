"""drop an unused column from sessions

The test runs in a normal browser, so there is no result of that kind to record.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-16 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '0005'
down_revision: Union[str, Sequence[str], None] = '0004'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_column('sessions', 'seb_verified')


def downgrade() -> None:
    """Downgrade schema."""
    op.add_column(
        'sessions',
        sa.Column('seb_verified', sa.Boolean(), server_default='false', nullable=False),
    )
