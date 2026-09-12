"""add_payment_status_and_payments_table

Revision ID: f87c41602cbc
Revises: dc38abb43d6b
Create Date: 2026-09-10 17:18:21.464652

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f87c41602cbc"
down_revision: Union[str, Sequence[str], None] = "dc38abb43d6b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""

    # payments table already exists in the database.
    # payment_status also already exists in orders.
    #
    # Therefore, this migration only needs to bring
    # the remaining orders columns to the intended schema.

    with op.batch_alter_table("orders") as batch_op:

        batch_op.alter_column(
            "status",
            existing_type=sa.VARCHAR(length=30),
            nullable=False
        )

        batch_op.alter_column(
            "created_at",
            existing_type=sa.DATETIME(),
            nullable=False
        )

        batch_op.alter_column(
            "updated_at",
            existing_type=sa.DATETIME(),
            nullable=False
        )


def downgrade() -> None:
    """Downgrade schema."""

    with op.batch_alter_table("orders") as batch_op:

        batch_op.alter_column(
            "updated_at",
            existing_type=sa.DATETIME(),
            nullable=True
        )

        batch_op.alter_column(
            "created_at",
            existing_type=sa.DATETIME(),
            nullable=True
        )

        batch_op.alter_column(
            "status",
            existing_type=sa.VARCHAR(length=30),
            nullable=True
        )

        batch_op.drop_column("payment_status")