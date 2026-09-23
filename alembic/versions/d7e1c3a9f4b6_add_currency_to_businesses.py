"""add currency to businesses

Revision ID: d7e1c3a9f4b6
Revises: c4a2f8e6b1d9
Create Date: 2026-09-24 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd7e1c3a9f4b6'
down_revision: Union[str, None] = 'c4a2f8e6b1d9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('businesses', sa.Column('currency', sa.String(length=3), server_default='USD', nullable=False))


def downgrade() -> None:
    op.drop_column('businesses', 'currency')
