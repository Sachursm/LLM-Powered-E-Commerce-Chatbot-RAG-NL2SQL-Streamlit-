"""rename_pending_to_pending_payment

Revision ID: abc123def456
Revises: f87c41602cbc
Create Date: 2026-09-11 ...

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'abc123def456'       # real ID
down_revision: Union[str, Sequence[str], None] = 'f87c41602cbc'  # real ID
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:

    op.execute(
        "UPDATE orders "
        "SET status = 'PENDING_PAYMENT' "
        "WHERE status = 'PENDING'"
    )


def downgrade() -> None:

    op.execute(
        "UPDATE orders "
        "SET status = 'PENDING' "
        "WHERE status = 'PENDING_PAYMENT'"
    )