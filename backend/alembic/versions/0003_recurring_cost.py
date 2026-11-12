"""recurring costs

Revision ID: 0003
Revises: 0002
"""
from alembic import op
import sqlalchemy as sa


revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('recurring_cost',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('vehicle_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('category', sa.String(length=40), nullable=False),
    sa.Column('amount_cents', sa.Integer(), nullable=False),
    sa.Column('every_months', sa.Integer(), nullable=False),
    sa.Column('start_date', sa.Date(), nullable=False),
    sa.Column('end_date', sa.Date(), nullable=True),
    sa.Column('remind_days', sa.Integer(), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.ForeignKeyConstraint(['vehicle_id'], ['vehicle.id'], name='fk_recurring_cost_vehicle_id_vehicle',
                            ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_recurring_cost_vehicle_id', 'recurring_cost', ['vehicle_id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_recurring_cost_vehicle_id', table_name='recurring_cost')
    op.drop_table('recurring_cost')
