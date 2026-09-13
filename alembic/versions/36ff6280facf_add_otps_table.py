"""add_otps_table

Revision ID: 36ff6280facf
Revises: 5efb97742e66
Create Date: 2026-09-13 19:55:49.861883

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '36ff6280facf'
down_revision: Union[str, Sequence[str], None] = '5efb97742e66'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:

    op.create_table('otps',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('email', sa.String(length=100), nullable=False),
        sa.Column('otp_code', sa.String(length=6), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_otps_email'), 'otps', ['email'], unique=False)


def downgrade() -> None:

    op.drop_index(op.f('ix_otps_email'), table_name='otps')
    op.drop_table('otps')