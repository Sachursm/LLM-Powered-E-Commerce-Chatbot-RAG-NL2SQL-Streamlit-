from datetime import datetime

from sqlalchemy import ForeignKey, String, DateTime
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


class DeliveryAgent(Base):
    __tablename__ = "delivery_agents"

    id: Mapped[int] = mapped_column(
        primary_key=True
    )

    # Links to the User account
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"),
        unique=True
    )

    # Which hub this agent belongs to
    hub_id: Mapped[int] = mapped_column(
        ForeignKey("delivery_hubs.id")
    )

    name: Mapped[str] = mapped_column(
        String(100)
    )

    phone: Mapped[str] = mapped_column(
        String(20)
    )

    # ACTIVE / INACTIVE
    status: Mapped[str] = mapped_column(
        String(20),
        default="ACTIVE"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow
    )

    # Relationships
    user: Mapped["User"] = relationship(
        back_populates="delivery_agent"
    )

    hub: Mapped["DeliveryHub"] = relationship(
        back_populates="agents"
    )