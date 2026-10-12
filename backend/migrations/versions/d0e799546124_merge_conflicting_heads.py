"""merge conflicting heads

Revision ID: d0e799546124
Revises: 099386ddc434, a1c3f7d9b2e4
Create Date: 2026-09-17 12:51:53.390677

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd0e799546124'
down_revision = ('099386ddc434', 'a1c3f7d9b2e4')
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
