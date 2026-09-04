"""add order ownership and order fields

Revision ID: dc38abb43d6b
Revises: f6d0675542fc
Create Date: 2026-09-01 15:56:53.803959
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# Revision identifiers, used by Alembic.
revision: str = "dc38abb43d6b"
down_revision: Union[str, Sequence[str], None] = "f6d0675542fc"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:

    # ---------------------------------------------------------
    # All required columns already exist in the database.
    #
    # orders:
    #   status
    #   created_at
    #   updated_at
    #
    # order_items:
    #   owner_id
    #   unit_price
    #   created_at
    #
    # Therefore, we do NOT add the columns again.
    # ---------------------------------------------------------

    # ---------------------------------------------------------
    # Add the foreign key from order_items.owner_id
    # to users.id.
    #
    # SQLite requires batch mode when adding a foreign key
    # constraint to an existing table.
    # ---------------------------------------------------------

    with op.batch_alter_table(
        "order_items",
        schema=None
    ) as batch_op:

        batch_op.create_foreign_key(
            "fk_order_items_owner_id_users",
            "users",
            ["owner_id"],
            ["id"]
        )