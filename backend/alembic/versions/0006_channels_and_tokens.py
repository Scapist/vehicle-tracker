"""Discord linking, preferred alert app, MCP access tokens

Revision ID: 0006
Revises: 0005

Plain ADD COLUMNs plus a new table (no batch rebuild of `user`, so nothing that points at it moves).
SQLite can't add a UNIQUE column, so uniqueness of discord_user_id is a unique index.
"""
from alembic import op
import sqlalchemy as sa


revision = '0006'
down_revision = '0005'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('user', sa.Column('discord_user_id', sa.BigInteger(), nullable=True))
    op.add_column('user', sa.Column('alert_channel', sa.String(length=20), nullable=True))
    op.create_index('ix_user_discord_user_id', 'user', ['discord_user_id'], unique=True)
    op.create_table(
        'api_token',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=80), nullable=False),
        sa.Column('token_hash', sa.String(length=64), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['user.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('token_hash'),
    )
    op.create_index('ix_api_token_user_id', 'api_token', ['user_id'])


def downgrade() -> None:
    op.drop_index('ix_api_token_user_id', table_name='api_token')
    op.drop_table('api_token')
    op.drop_index('ix_user_discord_user_id', table_name='user')
    with op.batch_alter_table('user') as batch_op:
        batch_op.drop_column('alert_channel')
        batch_op.drop_column('discord_user_id')
