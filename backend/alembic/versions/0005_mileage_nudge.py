"""mileage nudge setting per vehicle

Revision ID: 0005
Revises: 0004

A plain ADD COLUMN (no batch table rebuild), so the vehicle table and everything pointing at it stay put.
"""
from alembic import op
import sqlalchemy as sa


revision = '0005'
down_revision = '0004'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('vehicle', sa.Column('nudge_days', sa.Integer(), nullable=False, server_default='14'))


def downgrade() -> None:
    with op.batch_alter_table('vehicle') as batch_op:
        batch_op.drop_column('nudge_days')
