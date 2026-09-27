"""Ensure each order item has at most one seller payout.

Revision ID: a91f3e7d6b42
Revises: 13db0c4264c6
Create Date: 2026-09-27
"""

from alembic import op


revision = "a91f3e7d6b42"
down_revision = "13db0c4264c6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("seller_payouts") as batch_op:
        batch_op.create_unique_constraint(
            "uq_seller_payouts_order_item_id", ["order_item_id"]
        )


def downgrade() -> None:
    with op.batch_alter_table("seller_payouts") as batch_op:
        batch_op.drop_constraint(
            "uq_seller_payouts_order_item_id", type_="unique"
        )
