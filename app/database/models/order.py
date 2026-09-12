from datetime import datetime

from sqlalchemy import ForeignKey, String, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.database import Base

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.database.models.user import User
    from app.database.models.order_item import OrderItem
    from app.database.models.payment import Payment
    from app.database.models.address import Address
    from app.database.models.shipment import Shipment




class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(
        primary_key=True
    )

    # Customer who placed the order
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id")
    )

    # Current order status
    status: Mapped[str] = mapped_column(
        String(30),
        default="PENDING"
    )

    # Payment status
    payment_status: Mapped[str] = mapped_column(
        String(30),
        default="UNPAID"
    )

    # When the order was created
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow
    )

    # Last time the order was updated
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow
    )

    # Customer relationship
    user: Mapped["User"] = relationship(
        back_populates="orders"
    )

    # Order → OrderItems
    items: Mapped[list["OrderItem"]] = relationship(
        back_populates="order",
        cascade="all, delete-orphan"
    )

    # Order → Payments
    payments: Mapped[list["Payment"]] = relationship(
        back_populates="order",
        cascade="all, delete-orphan"
    )

    # Add column (after payment_status):
    shipping_address_id: Mapped[int | None] = mapped_column(
        ForeignKey("addresses.id"),
        nullable=True
    )

    # Add relationship:
    shipping_address: Mapped["Address | None"] = relationship()

    # Add relationship:
    shipments: Mapped[list["Shipment"]] = relationship(
        back_populates="order",
        cascade="all, delete-orphan"
    )