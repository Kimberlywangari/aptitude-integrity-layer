"""a password for each candidate who has an email

The candidate chooses it at their first sign-in. Only its bcrypt hash is stored. Candidates made
without an email (practice, old invitations) have none and sign in with the code alone.

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-24 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '0013'
down_revision: Union[str, Sequence[str], None] = '0012'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('candidates', sa.Column('password_hash', sa.String(length=100), nullable=True))
    # the email-and-password sign-in looks candidates up by email
    op.create_index('ix_candidates_email', 'candidates', ['email'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_candidates_email', table_name='candidates')
    op.drop_column('candidates', 'password_hash')
