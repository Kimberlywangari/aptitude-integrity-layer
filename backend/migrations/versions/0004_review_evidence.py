"""events, heartbeats, flags, decisions and complaints

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-15 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '0004'
down_revision: Union[str, Sequence[str], None] = '0003'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('events',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('session_id', sa.String(length=32), nullable=False),
    sa.Column('client_seq', sa.Integer(), nullable=False),
    sa.Column('type', sa.String(length=32), nullable=False),
    sa.Column('server_ts', sa.DateTime(timezone=True), nullable=False),
    sa.Column('received_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.ForeignKeyConstraint(['session_id'], ['sessions.id'], name=op.f('fk_events_session_id_sessions'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_events')),
    sa.UniqueConstraint('session_id', 'client_seq', name=op.f('uq_events_session_id'))
    )
    op.create_index('ix_events_session_id_server_ts', 'events', ['session_id', 'server_ts'], unique=False)

    op.create_table('heartbeats',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('session_id', sa.String(length=32), nullable=False),
    sa.Column('server_ts', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['session_id'], ['sessions.id'], name=op.f('fk_heartbeats_session_id_sessions'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_heartbeats'))
    )
    op.create_index('ix_heartbeats_session_id_server_ts', 'heartbeats', ['session_id', 'server_ts'], unique=False)

    op.create_table('flags',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('session_id', sa.String(length=32), nullable=False),
    sa.Column('kind', sa.String(length=32), nullable=False),
    sa.Column('weight', sa.Float(), nullable=False),
    sa.Column('server_ts', sa.DateTime(timezone=True), nullable=False),
    sa.Column('position', sa.Integer(), nullable=True),
    sa.Column('detail', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('source', sa.String(length=10), server_default='rule', nullable=False),
    sa.CheckConstraint("source in ('rule', 'ai')", name=op.f('ck_flags_source')),
    sa.ForeignKeyConstraint(['session_id'], ['sessions.id'], name=op.f('fk_flags_session_id_sessions'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_flags'))
    )
    op.create_index(op.f('ix_flags_session_id'), 'flags', ['session_id'], unique=False)

    op.create_table('decisions',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('session_id', sa.String(length=32), nullable=False),
    sa.Column('reviewer_id', sa.Integer(), nullable=True),
    sa.Column('outcome', sa.String(length=24), nullable=False),
    sa.Column('reason', sa.Text(), nullable=False),
    sa.Column('decided_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("outcome in ('no_concern', 'concern_noted', 'refer_for_follow_up')", name=op.f('ck_decisions_outcome')),
    sa.ForeignKeyConstraint(['reviewer_id'], ['reviewers.id'], name=op.f('fk_decisions_reviewer_id_reviewers'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['session_id'], ['sessions.id'], name=op.f('fk_decisions_session_id_sessions'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_decisions'))
    )
    op.create_index(op.f('ix_decisions_session_id'), 'decisions', ['session_id'], unique=False)

    op.create_table('complaints',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('session_id', sa.String(length=32), nullable=False),
    sa.Column('category', sa.String(length=10), nullable=False),
    sa.Column('text', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('status', sa.String(length=10), server_default='open', nullable=False),
    sa.CheckConstraint("category in ('camera', 'upload', 'other')", name=op.f('ck_complaints_category')),
    sa.CheckConstraint("status in ('open', 'reviewed')", name=op.f('ck_complaints_status')),
    sa.ForeignKeyConstraint(['session_id'], ['sessions.id'], name=op.f('fk_complaints_session_id_sessions'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_complaints'))
    )
    op.create_index(op.f('ix_complaints_session_id'), 'complaints', ['session_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_complaints_session_id'), table_name='complaints')
    op.drop_table('complaints')
    op.drop_index(op.f('ix_decisions_session_id'), table_name='decisions')
    op.drop_table('decisions')
    op.drop_index(op.f('ix_flags_session_id'), table_name='flags')
    op.drop_table('flags')
    op.drop_index('ix_heartbeats_session_id_server_ts', table_name='heartbeats')
    op.drop_table('heartbeats')
    op.drop_index('ix_events_session_id_server_ts', table_name='events')
    op.drop_table('events')
