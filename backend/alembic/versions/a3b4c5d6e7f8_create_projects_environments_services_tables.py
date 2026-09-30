"""create_projects_environments_services_tables

Revision ID: a3b4c5d6e7f8
Revises: e5f6a7b8c9d0
Create Date: 2026-09-30 22:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a3b4c5d6e7f8'
down_revision: Union[str, None] = 'e5f6a7b8c9d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Projects table
    op.create_table(
        'projects',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('organization_id', sa.UUID(), nullable=False),
        sa.Column('name', sa.String(length=128), nullable=False),
        sa.Column('slug', sa.String(length=128), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('organization_id', 'slug', name='uq_projects_organization_id_slug'),
        sa.UniqueConstraint('id', 'organization_id', name='uq_projects_id_organization_id'),
    )
    op.create_index(op.f('ix_projects_organization_id'), 'projects', ['organization_id'], unique=False)

    # 2. Environments table
    op.create_table(
        'environments',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('organization_id', sa.UUID(), nullable=False),
        sa.Column('project_id', sa.UUID(), nullable=False),
        sa.Column('name', sa.String(length=128), nullable=False),
        sa.Column('slug', sa.String(length=128), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(
            ['project_id', 'organization_id'],
            ['projects.id', 'projects.organization_id'],
            name='fk_environments_project_organization',
            ondelete='RESTRICT',
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('project_id', 'slug', name='uq_environments_project_id_slug'),
        sa.UniqueConstraint('id', 'project_id', 'organization_id', name='uq_environments_id_project_org'),
    )
    op.create_index(op.f('ix_environments_organization_id'), 'environments', ['organization_id'], unique=False)
    op.create_index(op.f('ix_environments_project_id'), 'environments', ['project_id'], unique=False)

    # 3. Services table
    op.create_table(
        'services',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('organization_id', sa.UUID(), nullable=False),
        sa.Column('project_id', sa.UUID(), nullable=False),
        sa.Column('environment_id', sa.UUID(), nullable=False),
        sa.Column('name', sa.String(length=128), nullable=False),
        sa.Column('slug', sa.String(length=128), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('service_type', sa.String(length=32), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['environment_id'], ['environments.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(
            ['environment_id', 'project_id', 'organization_id'],
            ['environments.id', 'environments.project_id', 'environments.organization_id'],
            name='fk_services_environment_project_org',
            ondelete='RESTRICT',
        ),
        sa.CheckConstraint(
            "service_type IN ('APPLICATION', 'WORKER', 'DATABASE', 'CACHE', 'QUEUE', 'OTHER')",
            name='ck_services_service_type',
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('environment_id', 'slug', name='uq_services_environment_id_slug'),
    )
    op.create_index(op.f('ix_services_organization_id'), 'services', ['organization_id'], unique=False)
    op.create_index(op.f('ix_services_project_id'), 'services', ['project_id'], unique=False)
    op.create_index(op.f('ix_services_environment_id'), 'services', ['environment_id'], unique=False)


def downgrade() -> None:
    # 3. Services table
    op.drop_index(op.f('ix_services_environment_id'), table_name='services')
    op.drop_index(op.f('ix_services_project_id'), table_name='services')
    op.drop_index(op.f('ix_services_organization_id'), table_name='services')
    op.drop_table('services')

    # 2. Environments table
    op.drop_index(op.f('ix_environments_project_id'), table_name='environments')
    op.drop_index(op.f('ix_environments_organization_id'), table_name='environments')
    op.drop_table('environments')

    # 1. Projects table
    op.drop_index(op.f('ix_projects_organization_id'), table_name='projects')
    op.drop_table('projects')
