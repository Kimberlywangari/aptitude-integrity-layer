"""staff accounts and audit log

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-14 22:40:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '0002'
down_revision: Union[str, Sequence[str], None] = '0001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('reviewers',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('email', sa.String(length=254), nullable=False),
    sa.Column('password_hash', sa.String(length=100), nullable=False),
    sa.Column('role', sa.String(length=10), server_default='reviewer', nullable=False),
    sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("role in ('reviewer', 'admin')", name=op.f('ck_reviewers_role')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_reviewers')),
    sa.UniqueConstraint('email', name=op.f('uq_reviewers_email'))
    )
    op.create_table('audit_log',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('reviewer_id', sa.Integer(), nullable=True),
    sa.Column('action', sa.String(length=20), nullable=False),
    sa.Column('session_id', sa.String(length=32), nullable=True),
    sa.Column('ts', sa.DateTime(timezone=True), nullable=False),
    sa.Column('detail', sa.Text(), nullable=True),
    sa.CheckConstraint("action in ('login', 'decision', 'video_view', 'video_purged')", name=op.f('ck_audit_log_action')),
    sa.ForeignKeyConstraint(['reviewer_id'], ['reviewers.id'], name=op.f('fk_audit_log_reviewer_id_reviewers'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['session_id'], ['sessions.id'], name=op.f('fk_audit_log_session_id_sessions')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_audit_log'))
    )
    op.create_index(op.f('ix_audit_log_ts'), 'audit_log', ['ts'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_audit_log_ts'), table_name='audit_log')
    op.drop_table('audit_log')
    op.drop_table('reviewers')
