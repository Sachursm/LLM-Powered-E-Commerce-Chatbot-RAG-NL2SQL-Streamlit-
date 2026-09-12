from datetime import datetime

from sqlalchemy import (
    ForeignKey, String, DateTime, Text
)
from sqlalchemy.orm import (
    Mapped, mapped_column, relationship
)

from app.database.database import Base

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.database.models.order import Order
    from app.database.models.user import User


class Shipment(Base):
    __tablename__ = "shipments"

    id: Mapped[int] = mapped_column(
        primary_key=True
    )

    # Which order this shipment belongs to
    order_id: Mapped[int] = mapped_column(
        ForeignKey("orders.id")
    )

    # Seller/Admin who owns the items
    seller_id: Mapped[int] = mapped_column(
        ForeignKey("users.id")
    )

    # Customer who placed the order
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("users.id")
    )

    # Current shipment status
    # PROCESSING → SHIPPED → IN_TRANSIT →
    # OUT_FOR_DELIVERY → DELIVERED
    # or CANCELLED / DELIVERY_FAILED
    status: Mapped[str] = mapped_column(
        String(30),
        default="PROCESSING"
    )

    # DELIVERY or RETURN
    type: Mapped[str] = mapped_column(
        String(20),
        default="DELIVERY"
    )

    # Shipping address snapshot
    shipping_address_id: Mapped[int | None] = (
        mapped_column(
            ForeignKey("addresses.id"),
            nullable=True
        )
    )

    # Who shipped it (user who clicked ship)
    shipped_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"),
        nullable=True
    )

    # When it was shipped
    shipped_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True
    )

    # When it was delivered
    delivered_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True
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
    order: Mapped["Order"] = relationship(
        back_populates="shipments"
    )

    tracking_events: Mapped[list["ShipmentTracking"]] = (
        relationship(
            back_populates="shipment",
            cascade="all, delete-orphan",
            order_by="ShipmentTracking.created_at"
        )
    )

        # Current hub location
    current_hub_id: Mapped[int | None] = mapped_column(
        ForeignKey("delivery_hubs.id"),
        nullable=True
    )

    # Assigned delivery agent
    assigned_agent_id: Mapped[int | None] = mapped_column(
        ForeignKey("delivery_agents.id"),
        nullable=True
    )

      


class ShipmentTracking(Base):
    __tablename__ = "shipment_tracking"

    id: Mapped[int] = mapped_column(
        primary_key=True
    )

    # Which shipment
    shipment_id: Mapped[int] = mapped_column(
        ForeignKey("shipments.id")
    )

    # Status at this point
    status: Mapped[str] = mapped_column(
        String(30)
    )

    # Description of what happened
    description: Mapped[str] = mapped_column(
        Text
    )

    # Who created this event
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"),
        nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow
    )

    # Relationships
    shipment: Mapped["Shipment"] = relationship(
        back_populates="tracking_events"
    )

  