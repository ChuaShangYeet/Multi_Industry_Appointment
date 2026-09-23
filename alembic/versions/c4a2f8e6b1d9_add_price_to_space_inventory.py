"""add price to space_inventory

Revision ID: c4a2f8e6b1d9
Revises: b3f7e9a1c5d2
Create Date: 2026-09-23 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c4a2f8e6b1d9'
down_revision: Union[str, None] = 'b3f7e9a1c5d2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('space_inventory', sa.Column('price', sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column('space_inventory', 'price')
