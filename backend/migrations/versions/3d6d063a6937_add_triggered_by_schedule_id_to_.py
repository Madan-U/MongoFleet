"""add triggered_by_schedule_id to operations

Revision ID: 3d6d063a6937
Revises: d0e799546124
Create Date: 2026-09-18 17:50:07.127176

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '3d6d063a6937'
down_revision = 'd0e799546124'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('operations', sa.Column('triggered_by_schedule_id', sa.Integer(), sa.ForeignKey('scheduled_operations.id'), nullable=True))
    pass


def downgrade():
    op.drop_column('operations', 'triggered_by_schedule_id')
    pass
