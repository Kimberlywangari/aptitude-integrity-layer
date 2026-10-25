"""a name and an email for each candidate, and the outbox of emails to send

The name and email are for the invitation and result emails and the admin's list only. The outbox
holds each email until it is sent, one row per (candidate, kind).

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-24 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '0012'
down_revision: Union[str, Sequence[str], None] = '0011'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('candidates', sa.Column('full_name', sa.String(length=200), nullable=True))
    op.add_column('candidates', sa.Column('email', sa.String(length=254), nullable=True))
    op.create_index(
        'uq_candidates_sitting_email',
        'candidates',
        ['sitting_id', 'email'],
        unique=True,
        postgresql_where=sa.text('email is not null'),
    )
    op.create_table(
        'email_outbox',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('candidate_id', sa.String(length=32), nullable=True),
        sa.Column('kind', sa.String(length=12), nullable=False),
        sa.Column('to_address', sa.String(length=254), nullable=False),
        sa.Column('subject', sa.String(length=200), nullable=False),
        sa.Column('body', sa.Text(), nullable=True),
        sa.Column('status', sa.String(length=8), server_default='queued', nullable=False),
        sa.Column('attempts', sa.Integer(), server_default='0', nullable=False),
        sa.Column('error', sa.String(length=300), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('sent_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['candidate_id'], ['candidates.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('candidate_id', 'kind', name='uq_outbox_candidate_kind'),
    )
    op.create_index('ix_email_outbox_candidate_id', 'email_outbox', ['candidate_id'])
    op.create_index('ix_email_outbox_status', 'email_outbox', ['status'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('email_outbox')
    op.drop_index('uq_candidates_sitting_email', table_name='candidates')
    op.drop_column('candidates', 'email')
    op.drop_column('candidates', 'full_name')
