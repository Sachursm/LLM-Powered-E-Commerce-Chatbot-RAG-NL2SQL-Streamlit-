"""add_addresses_table_and_order_shipping_address

Revision ID: 78b5a2d61f6f
Revises: abc123def456
Create Date: 2026-09-11 20:32:51.677682

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '78b5a2d61f6f'
down_revision: Union[str, Sequence[str], None] = 'abc123def456'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:

    # addresses table already exists from
    # the previous failed migration attempt

    with op.batch_alter_table('orders') as batch_op:

        batch_op.add_column(
            sa.Column(
                'shipping_address_id',
                sa.Integer(),
                nullable=True
            )
        )

        batch_op.create_foreign_key(
            'fk_orders_shipping_address',
            'addresses',
            ['shipping_address_id'],
            ['id']
        )


def downgrade() -> None:

    with op.batch_alter_table('orders') as batch_op:

        batch_op.drop_constraint(
            'fk_orders_shipping_address',
            type_='foreignkey'
        )

        batch_op.drop_column('shipping_address_id')

    op.drop_table('addresses')