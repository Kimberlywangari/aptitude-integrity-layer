"""audit log: an `admin` action

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-15 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy.schema import conv

# revision identifiers, used by Alembic.
revision: str = '0003'
down_revision: Union[str, Sequence[str], None] = '0002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Not op.f(): that needs a running migration, and `alembic heads` and `history` import this file
# without one. conv is what op.f returns (a name that is already final).
CONSTRAINT = conv('ck_audit_log_action')


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_constraint(CONSTRAINT, 'audit_log', type_='check')
    op.create_check_constraint(
        CONSTRAINT,
        'audit_log',
        "action in ('login', 'decision', 'video_view', 'video_purged', 'admin')",
    )


def downgrade() -> None:
    """Downgrade schema. Admin rows go: the older constraint has no place for them."""
    op.execute("delete from audit_log where action = 'admin'")
    op.drop_constraint(CONSTRAINT, 'audit_log', type_='check')
    op.create_check_constraint(
        CONSTRAINT,
        'audit_log',
        "action in ('login', 'decision', 'video_view', 'video_purged')",
    )
