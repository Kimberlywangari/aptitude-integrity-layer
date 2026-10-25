"""invitations belong to a sitting; Cytonn's pictures and passages

- `candidates.sitting_id`: an invitation made for a sitting starts that sitting's paper, whatever
  other sittings are open. Invitations made before this have none and keep the old rule (the newest
  open sitting).
- `sittings.question_mode` also allows `practice` (the made-up bank only) and `cytonn` (Cytonn's
  questions only). Sittings that already existed drew from the one bank there was, which held only
  made-up questions, so they become `practice` and keep drawing from exactly that.
- `question_images`: the pictures some of Cytonn's questions depend on, copied onto our server so a
  candidate's test never depends on Cytonn's website being up. `questions.passage_key` groups
  questions that share one reading passage, so a paper does not ask about it ten times.

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-23 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '0010'
down_revision: Union[str, Sequence[str], None] = '0009'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('candidates', sa.Column('sitting_id', sa.Integer(), nullable=True))
    op.create_foreign_key(
        op.f('fk_candidates_sitting_id_sittings'), 'candidates', 'sittings', ['sitting_id'], ['id']
    )
    op.create_index(op.f('ix_candidates_sitting_id'), 'candidates', ['sitting_id'])
    # Attach the invitations that already exist to the sitting they belong to, so the new counts are
    # exact from the start: the sitting they already have a session in, else the newest open one,
    # which is where they would have opened under the old rule.
    op.execute(
        "update candidates c set sitting_id = ("
        "select s.sitting_id from sessions s where s.candidate_id = c.id "
        "order by s.created_at desc limit 1) "
        "where c.sitting_id is null "
        "and exists (select 1 from sessions s where s.candidate_id = c.id)"
    )
    op.execute(
        "update candidates set sitting_id = ("
        "select id from sittings where status = 'open' order by id desc limit 1) "
        "where sitting_id is null"
    )

    op.drop_constraint(op.f('ck_sittings_question_mode'), 'sittings', type_='check')
    op.execute("update sittings set question_mode = 'practice' where question_mode = 'bank'")
    op.create_check_constraint(
        op.f('ck_sittings_question_mode'),
        'sittings',
        "question_mode in ('bank', 'practice', 'cytonn', 'ai')",
    )

    op.add_column('questions', sa.Column('passage_key', sa.String(length=16), nullable=True))
    op.create_index(op.f('ix_questions_passage_key'), 'questions', ['passage_key'])

    op.create_table(
        'question_images',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('question_id', sa.String(length=16), nullable=False),
        sa.Column('position', sa.Integer(), nullable=False),
        sa.Column('content_type', sa.String(length=40), nullable=False),
        sa.Column('sha256', sa.String(length=64), nullable=False),
        sa.Column('source_url', sa.Text(), nullable=False),
        sa.Column('data', sa.LargeBinary(), nullable=False),
        sa.ForeignKeyConstraint(
            ['question_id'],
            ['questions.id'],
            name=op.f('fk_question_images_question_id_questions'),
            ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_question_images')),
        sa.UniqueConstraint(
            'question_id', 'position', name=op.f('uq_question_images_question_id')
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('question_images')
    op.drop_index(op.f('ix_questions_passage_key'), table_name='questions')
    op.drop_column('questions', 'passage_key')

    op.drop_constraint(op.f('ck_sittings_question_mode'), 'sittings', type_='check')
    op.execute(
        "update sittings set question_mode = 'bank' where question_mode in ('practice', 'cytonn')"
    )
    op.create_check_constraint(
        op.f('ck_sittings_question_mode'), 'sittings', "question_mode in ('bank', 'ai')"
    )

    op.drop_index(op.f('ix_candidates_sitting_id'), table_name='candidates')
    op.drop_constraint(op.f('fk_candidates_sitting_id_sittings'), 'candidates', type_='foreignkey')
    op.drop_column('candidates', 'sitting_id')
