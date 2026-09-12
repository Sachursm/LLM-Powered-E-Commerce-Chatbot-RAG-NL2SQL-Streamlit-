from datetime import datetime

from sqlalchemy import ForeignKey, DateTime
from sqlalchemy.orm import (
    Mapped, mapped_column, relationship
)

from app.database.database import Base

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.database.models.user import User
    from app.database.models.delivery_hub import (
        DeliveryHub
    )


class HubManager(Base):
    __tablename__ = "hub_managers"

    id: Mapped[int] = mapped_column(
        primary_key=True
    )

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"),
        unique=True
    )

    hub_id: Mapped[int] = mapped_column(
        ForeignKey("delivery_hubs.id")
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow
    )

    # Relationships
    user: Mapped["User"] = relationship(
        back_populates="hub_manager"
    )

    hub: Mapped["DeliveryHub"] = relationship(
        back_populates="managers"
    )