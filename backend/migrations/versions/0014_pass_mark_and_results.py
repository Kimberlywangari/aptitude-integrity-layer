"""a pass mark for each sitting, and a result for each candidate

`sittings.pass_mark` is the number of correct answers needed. Empty means none is set, and then
nothing is turned down for its score.

On `sessions`: `result` is what a person (or the pass-mark rule, for a low score) decided, `pass`
or `fail`; `result_basis` says which (`score` or `review`); `result_reason` is the short plain
sentence the candidate is told; `result_by` is the staff account, empty when the rule did it.
`appeal_at` is set by hand when a candidate who failed has written to ask for a second look.

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-24 21:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '0014'
down_revision: Union[str, Sequence[str], None] = '0013'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('sittings', sa.Column('pass_mark', sa.Integer(), nullable=True))
    op.add_column('sessions', sa.Column('result', sa.String(length=4), nullable=True))
    op.add_column('sessions', sa.Column('result_basis', sa.String(length=6), nullable=True))
    op.add_column('sessions', sa.Column('result_reason', sa.String(length=300), nullable=True))
    op.add_column('sessions', sa.Column('result_by', sa.Integer(), nullable=True))
    op.create_foreign_key(
        op.f('fk_sessions_result_by_reviewers'),
        'sessions',
        'reviewers',
        ['result_by'],
        ['id'],
        ondelete='SET NULL',
    )
    op.add_column('sessions', sa.Column('result_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('sessions', sa.Column('appeal_at', sa.DateTime(timezone=True), nullable=True))
    op.create_check_constraint(
        op.f('ck_sessions_result'), 'sessions', "result in ('pass', 'fail')"
    )
    op.create_check_constraint(
        op.f('ck_sessions_result_basis'), 'sessions', "result_basis in ('score', 'review')"
    )
    # the outcomes list and the emails look a result email up by kind and state
    op.create_index('ix_email_outbox_kind_status', 'email_outbox', ['kind', 'status'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_email_outbox_kind_status', table_name='email_outbox')
    op.drop_constraint(op.f('ck_sessions_result_basis'), 'sessions', type_='check')
    op.drop_constraint(op.f('ck_sessions_result'), 'sessions', type_='check')
    op.drop_constraint(op.f('fk_sessions_result_by_reviewers'), 'sessions', type_='foreignkey')
    for column in ('appeal_at', 'result_at', 'result_by', 'result_reason', 'result_basis', 'result'):
        op.drop_column('sessions', column)
    op.drop_column('sittings', 'pass_mark')
