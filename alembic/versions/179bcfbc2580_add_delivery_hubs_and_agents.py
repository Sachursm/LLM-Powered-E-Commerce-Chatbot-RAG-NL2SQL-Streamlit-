"""add_delivery_hubs_and_agents

Revision ID: 179bcfbc2580
Revises: 7c468b03198d
Create Date: 2026-09-12 20:34:33.289711

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '179bcfbc2580'
down_revision: Union[str, Sequence[str], None] = '7c468b03198d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None
def upgrade() -> None:
    # Columns current_hub_id and assigned_agent_id
    # already exist from a previous migration attempt.
    pass


def downgrade() -> None:

    with op.batch_alter_table('shipments') as batch_op:

        batch_op.drop_column('assigned_agent_id')
        batch_op.drop_column('current_hub_id')