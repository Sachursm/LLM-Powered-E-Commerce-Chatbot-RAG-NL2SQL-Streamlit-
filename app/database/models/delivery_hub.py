from datetime import datetime

from sqlalchemy import String, DateTime
from sqlalchemy.orm import (
    Mapped, mapped_column, relationship
)

from app.database.database import Base

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.database.models.delivery_agent import (
        DeliveryAgent
    )
    from app.database.models.hub_manager import HubManager




class DeliveryHub(Base):
    __tablename__ = "delivery_hubs"

    id: Mapped[int] = mapped_column(
        primary_key=True
    )

    name: Mapped[str] = mapped_column(
        String(100)
    )

    address: Mapped[str] = mapped_column(
        String(255)
    )

    city: Mapped[str] = mapped_column(
        String(100)
    )

    state: Mapped[str] = mapped_column(
        String(100)
    )

    pincode: Mapped[str] = mapped_column(
        String(10)
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

    # Hub → Agents
    agents: Mapped[list["DeliveryAgent"]] = relationship(
        back_populates="hub",
        cascade="all, delete-orphan"
    )

    # Add relationship (after agents):
    managers: Mapped[list["HubManager"]] = relationship(
        back_populates="hub",
        cascade="all, delete-orphan"
    )