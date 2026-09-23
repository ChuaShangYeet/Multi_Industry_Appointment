"""add hotel_room_items

Revision ID: e8b5f2c9a3d1
Revises: d7e1c3a9f4b6
Create Date: 2026-09-25 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e8b5f2c9a3d1'
down_revision: Union[str, None] = 'd7e1c3a9f4b6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'hotel_room_items',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('appointment_id', sa.Integer(), nullable=False),
        sa.Column('space_inventory_id', sa.Integer(), nullable=False),
        sa.Column('quantity', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.ForeignKeyConstraint(['appointment_id'], ['appointments.id']),
        sa.ForeignKeyConstraint(['space_inventory_id'], ['space_inventory.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_hotel_room_items_appointment_id'), 'hotel_room_items', ['appointment_id'], unique=False)
    op.create_index(op.f('ix_hotel_room_items_space_inventory_id'), 'hotel_room_items', ['space_inventory_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_hotel_room_items_space_inventory_id'), table_name='hotel_room_items')
    op.drop_index(op.f('ix_hotel_room_items_appointment_id'), table_name='hotel_room_items')
    op.drop_table('hotel_room_items')
