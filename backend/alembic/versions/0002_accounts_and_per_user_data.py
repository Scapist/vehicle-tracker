"""accounts and per-user data

Revision ID: 0002
Revises: 0001

Existing vehicles and date items keep user_id NULL; the first account created claims them.
"""
from alembic import op
import sqlalchemy as sa


revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None

# 0001 created vehicle.nickname's unique constraint without a name; this lets batch mode find it
NAMING = {"uq": "uq_%(table_name)s_%(column_0_name)s"}


def upgrade() -> None:
    op.create_table('user',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('email', sa.String(length=254), nullable=False),
    sa.Column('name', sa.String(length=80), nullable=False),
    sa.Column('password_hash', sa.String(length=255), nullable=False),
    sa.Column('is_owner', sa.Boolean(), nullable=False),
    sa.Column('session_version', sa.Integer(), nullable=False),
    sa.Column('telegram_chat_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('email', name='uq_user_email'),
    sa.UniqueConstraint('telegram_chat_id', name='uq_user_telegram_chat_id')
    )
    op.create_table('invite',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('created_by', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('used_by', sa.Integer(), nullable=True),
    sa.Column('used_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['created_by'], ['user.id'], name='fk_invite_created_by_user', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['used_by'], ['user.id'], name='fk_invite_used_by_user', ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('token_hash', name='uq_invite_token_hash')
    )
    with op.batch_alter_table('date_item', schema=None) as batch_op:
        batch_op.add_column(sa.Column('user_id', sa.Integer(), nullable=True))
        batch_op.create_index('ix_date_item_user_id', ['user_id'], unique=False)
        batch_op.create_foreign_key('fk_date_item_user_id_user', 'user', ['user_id'], ['id'], ondelete='CASCADE')

    with op.batch_alter_table('notification_outbox', schema=None) as batch_op:
        batch_op.add_column(sa.Column('recipient', sa.String(length=120), nullable=True))

    with op.batch_alter_table('vehicle', schema=None, naming_convention=NAMING) as batch_op:
        batch_op.drop_constraint('uq_vehicle_nickname', type_='unique')  # nicknames are unique per user now
        batch_op.add_column(sa.Column('user_id', sa.Integer(), nullable=True))
        batch_op.create_index('ix_vehicle_user_id', ['user_id'], unique=False)
        batch_op.create_unique_constraint('uq_vehicle_user_id_nickname', ['user_id', 'nickname'])
        batch_op.create_foreign_key('fk_vehicle_user_id_user', 'user', ['user_id'], ['id'], ondelete='CASCADE')


def downgrade() -> None:
    with op.batch_alter_table('vehicle', schema=None) as batch_op:
        batch_op.drop_constraint('fk_vehicle_user_id_user', type_='foreignkey')
        batch_op.drop_constraint('uq_vehicle_user_id_nickname', type_='unique')
        batch_op.drop_index('ix_vehicle_user_id')
        batch_op.drop_column('user_id')
        batch_op.create_unique_constraint('uq_vehicle_nickname', ['nickname'])

    with op.batch_alter_table('notification_outbox', schema=None) as batch_op:
        batch_op.drop_column('recipient')

    with op.batch_alter_table('date_item', schema=None) as batch_op:
        batch_op.drop_constraint('fk_date_item_user_id_user', type_='foreignkey')
        batch_op.drop_index('ix_date_item_user_id')
        batch_op.drop_column('user_id')

    op.drop_table('invite')
    op.drop_table('user')
