"""custom service types

Revision ID: 0004
Revises: 0003
"""
from alembic import op
import sqlalchemy as sa


revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('service_type') as batch_op:
        batch_op.add_column(sa.Column('user_id', sa.Integer(), nullable=True))
        batch_op.create_index('ix_service_type_user_id', ['user_id'], unique=False)
        batch_op.create_foreign_key('fk_service_type_user_id_user', 'user', ['user_id'], ['id'], ondelete='CASCADE')


def downgrade() -> None:
    # custom types stay (shared from then on) so service history that uses them keeps its names
    with op.batch_alter_table('service_type') as batch_op:
        batch_op.drop_constraint('fk_service_type_user_id_user', type_='foreignkey')
        batch_op.drop_index('ix_service_type_user_id')
        batch_op.drop_column('user_id')
