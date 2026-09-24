"""add dynamic pricing to space_inventory

Revision ID: 9170fc80c74a
Revises: 7af203e8fbdd
Create Date: 2026-09-24 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9170fc80c74a'
down_revision: Union[str, None] = '7af203e8fbdd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'space_inventory',
        sa.Column('is_dynamic_pricing_enabled', sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column('space_inventory', 'is_dynamic_pricing_enabled')
