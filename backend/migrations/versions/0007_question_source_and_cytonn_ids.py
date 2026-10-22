"""question source and Cytonn ids

A question says where it came from, so a real question does not need a statistics row to count as
real, and keeps Cytonn's ids so a re-fetch updates it in place.

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-22 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '0007'
down_revision: Union[str, Sequence[str], None] = '0006'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'questions',
        sa.Column('source', sa.String(length=10), server_default='synthetic', nullable=False),
    )
    op.add_column('questions', sa.Column('cytonn_id', sa.Integer(), nullable=True))
    op.create_check_constraint(
        op.f('ck_questions_source'), 'questions', "source in ('cytonn', 'synthetic')"
    )
    op.create_unique_constraint(op.f('uq_questions_cytonn_id'), 'questions', ['cytonn_id'])
    op.add_column('options', sa.Column('cytonn_id', sa.Integer(), nullable=True))
    op.create_unique_constraint(
        op.f('uq_options_question_cytonn_id'), 'options', ['question_id', 'cytonn_id']
    )
    # Until now a question was real when its statistics came from Cytonn.
    op.execute(
        "update questions set source = 'cytonn' "
        "where id in (select question_id from question_stats where source = 'cytonn')"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(op.f('uq_options_question_cytonn_id'), 'options', type_='unique')
    op.drop_column('options', 'cytonn_id')
    op.drop_constraint(op.f('uq_questions_cytonn_id'), 'questions', type_='unique')
    op.drop_constraint(op.f('ck_questions_source'), 'questions', type_='check')
    op.drop_column('questions', 'cytonn_id')
    op.drop_column('questions', 'source')
