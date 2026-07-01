"""chat and documents

Revision ID: 037830678014
Revises: 39f3f257c330
Create Date: 2026-07-01 13:58:50.914776

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '037830678014'
down_revision: Union[str, Sequence[str], None] = '39f3f257c330'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    userrole = sa.Enum('employee', 'manager', 'admin', 'superadmin', name='userrole')
    userrole.create(op.get_bind(), checkfirst=True)
    op.alter_column(
        'users', 'role',
        existing_type=sa.VARCHAR(length=20),
        type_=userrole,
        existing_nullable=False,
        postgresql_using='role::userrole',
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column(
        'users', 'role',
        existing_type=sa.Enum('employee', 'manager', 'admin', 'superadmin', name='userrole'),
        type_=sa.VARCHAR(length=20),
        existing_nullable=False,
        postgresql_using='role::varchar',
    )
    sa.Enum(name='userrole').drop(op.get_bind(), checkfirst=True)
