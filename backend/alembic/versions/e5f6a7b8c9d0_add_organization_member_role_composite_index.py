"""add_organization_member_role_composite_index

Revision ID: e5f6a7b8c9d0
Revises: d4e91a2b3c4d
Create Date: 2026-09-26 22:50:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e5f6a7b8c9d0'
down_revision: Union[str, None] = 'd4e91a2b3c4d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        'ix_organization_members_organization_id_role',
        'organization_members',
        ['organization_id', 'role'],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        'ix_organization_members_organization_id_role',
        table_name='organization_members',
    )
