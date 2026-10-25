"""AI-written questions

A sitting can have its questions written by an AI for each candidate (`question_mode = 'ai'`). A
candidate's paper is then written in the background after their session is created, so a session
says whether its paper is `pending`, `ready` or `failed`. A written question is an ordinary row in
`questions` with source `ai`, plus the working the writer gave and which model wrote it.

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-23 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '0009'
down_revision: Union[str, Sequence[str], None] = '0008'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'sittings',
        sa.Column('question_mode', sa.String(length=8), server_default='bank', nullable=False),
    )
    op.create_check_constraint(
        op.f('ck_sittings_question_mode'), 'sittings', "question_mode in ('bank', 'ai')"
    )

    op.add_column(
        'sessions',
        sa.Column('paper_status', sa.String(length=10), server_default='ready', nullable=False),
    )
    op.add_column('sessions', sa.Column('paper_error', sa.String(length=200), nullable=True))
    op.create_check_constraint(
        op.f('ck_sessions_paper_status'),
        'sessions',
        "paper_status in ('pending', 'ready', 'failed')",
    )

    op.add_column('questions', sa.Column('explanation', sa.Text(), nullable=True))
    op.add_column('questions', sa.Column('written_by', sa.String(length=80), nullable=True))
    op.drop_constraint(op.f('ck_questions_source'), 'questions', type_='check')
    op.create_check_constraint(
        op.f('ck_questions_source'), 'questions', "source in ('cytonn', 'synthetic', 'ai')"
    )


def downgrade() -> None:
    """Downgrade schema.

    Questions an AI wrote have no place in the older constraint, so they go first, and the answers
    of any session that drew one go with them: without the question they cannot be read.
    """
    op.execute(
        "delete from session_questions where question_id in "
        "(select id from questions where source = 'ai')"
    )
    op.execute("delete from questions where source = 'ai'")
    op.drop_constraint(op.f('ck_questions_source'), 'questions', type_='check')
    op.create_check_constraint(
        op.f('ck_questions_source'), 'questions', "source in ('cytonn', 'synthetic')"
    )
    op.drop_column('questions', 'written_by')
    op.drop_column('questions', 'explanation')

    op.drop_constraint(op.f('ck_sessions_paper_status'), 'sessions', type_='check')
    op.drop_column('sessions', 'paper_error')
    op.drop_column('sessions', 'paper_status')

    op.drop_constraint(op.f('ck_sittings_question_mode'), 'sittings', type_='check')
    op.drop_column('sittings', 'question_mode')
