"""add_hub_managers_table

Revision ID: 304d44d7141b
Revises: f23af82093b9
Create Date: 2026-09-12 21:47:29.013876

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '304d44d7141b'
down_revision: Union[str, Sequence[str], None] = 'f23af82093b9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:

    op.create_table('hub_managers',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('hub_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['hub_id'], ['delivery_hubs.id'], ),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id')
    )

    # Foreign keys for current_hub_id and assigned_agent_id
    # already exist in the shipments table from a
    # previous migration. Skipping.


def downgrade() -> None:

    op.drop_table('hub_managers')