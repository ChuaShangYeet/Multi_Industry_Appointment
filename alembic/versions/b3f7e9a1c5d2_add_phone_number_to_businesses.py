"""add phone_number to businesses

Revision ID: b3f7e9a1c5d2
Revises: 774be5dfe273
Create Date: 2026-09-23 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b3f7e9a1c5d2'
down_revision: Union[str, None] = '774be5dfe273'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('businesses', sa.Column('phone_number', sa.String(length=32), nullable=True))


def downgrade() -> None:
    op.drop_column('businesses', 'phone_number')
