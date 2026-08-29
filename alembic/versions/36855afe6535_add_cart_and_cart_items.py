from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '36855afe6535'
down_revision: Union[str, Sequence[str], None] = '9096ea259c2c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("cart_items", schema=None) as batch_op:
        batch_op.drop_column("seller_id")


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("cart_items", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "seller_id",
                sa.Integer(),
                nullable=True
            )
        )

        batch_op.create_foreign_key(
            "fk_cart_items_seller_id_users",
            "users",
            ["seller_id"],
            ["id"],
            ondelete="SET NULL"
        )

        batch_op.create_index(
            "ix_cart_items_seller_id",
            ["seller_id"],
            unique=False
        )